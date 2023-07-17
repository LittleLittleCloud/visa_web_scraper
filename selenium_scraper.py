# from pyvirtualdisplay import Display
import os
import sys
import time

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import ElementNotInteractableException
from selenium.webdriver.chrome.options import Options
import random
from selenium.webdriver.common.by import By
from azure.data.tables import TableServiceClient
from azure.data.tables import TableServiceClient

from telegram import send_message
import omegaconf
import datetime
import time

conf = omegaconf.OmegaConf.load('config.yaml')
COUNTRY_CODE = conf.COUNTRY_CODE
BASE_URL = f'https://ais.usvisa-info.com/en-{COUNTRY_CODE}/niv'
from azure.core.credentials import AzureNamedKeyCredential

AZURE_STORAGE_ACCOUNT = conf.AZURE_STORAGE_ACCOUNT
AZURE_STORAGE_KEY = conf.AZURE_STORAGE_ACCESS_KEY
credential = AzureNamedKeyCredential(AZURE_STORAGE_ACCOUNT, AZURE_STORAGE_KEY)
service = TableServiceClient(endpoint=f"https://{AZURE_STORAGE_ACCOUNT}.table.core.windows.net", credential=credential)
candidates = conf.ACCOUNTS
def get_next_account():
    while True:
        for candidate in candidates:
            print(candidate)
            yield candidate.email, candidate.password, candidate.group_id, candidate.visa_type, candidate.tcn

def log_in(driver, user, pwd):
    if driver.current_url != BASE_URL + '/users/sign_in':
        print('Already logged.')
        print(driver.current_url)
        return

    print('Logging in.')

    # Clicking the first prompt, if there is one
    try:
        element = driver.find_element(By.XPATH, '/html/body/div/div[3]/div/button')
        # move to element
        webdriver.ActionChains(driver).move_to_element(element).click(element).perform()
    except:
        pass
    # Filling the user and password
    user_box = driver.find_element(By.NAME, 'user[email]')

    # move to element
    webdriver.ActionChains(driver).move_to_element(user_box).click(user_box).perform()
    # sends the user one character at a time
    for char in user:
        user_box.send_keys(char)
        # sleep a random time between 0.1 and 0.2 seconds
        time.sleep(random.uniform(0.1, 0.2))
    random_time = random.randint(5, 10)
    time.sleep(random_time)
    password_box = driver.find_element(By.NAME, 'user[password]')
    # move to element
    webdriver.ActionChains(driver).move_to_element(password_box).click(password_box).perform()
    # sends the password one character at a time
    for char in pwd:
        password_box.send_keys(char)
        # sleep a random time between 0.1 and 0.2 seconds
        time.sleep(random.uniform(0.1, 0.2))

    random_time = random.randint(5, 10)
    time.sleep(random_time)
    # Clicking the checkbox
    element = driver.find_element(By.XPATH, '//*[@id="sign_in_form"]/div/label/div')
    
    # move to element
    webdriver.ActionChains(driver).move_to_element(element).click(element).perform()

    # Clicking 'Sign in'
    element = driver.find_element(By.XPATH, '//*[@id="sign_in_form"]/p/input')
    # move to element
    # move mouse randomly
    webdriver.ActionChains(driver).move_to_element(element).click(element).perform()

    # Waiting for the page to load.
    # 5 seconds may be ok for a computer, but it doesn't seem enougn for the Raspberry Pi 4.
    time.sleep(10)
    print('Logged in.')


def has_website_changed(driver, user, pwd, url, no_appointment_text):
    '''Checks for changes in the site. Returns True if a change was found.'''
    # Log in
    while True:
        try:
            driver.get(url)
            log_in(driver, user, pwd)
            break
        except ElementNotInteractableException:
            time.sleep(5)

    # # For debugging false positives.
    # with open('debugging/page_source.html', 'w', encoding='utf-8') as f:
    #     f.write(driver.page_source)

    # Getting main text
    try:
        main_page = driver.find_element(By.ID, 'main')

        # For debugging false positives.
        with open('debugging/main_page', 'w') as f:
            f.write(main_page.text)
        # If the "no appointment" text is not found return True. A change was found.
        return no_appointment_text not in main_page.text, main_page.text
    except:
        print('No main page found.')
        return False, ''

    

def retrieve_earliest_date(content: str, city: str):
    # example
    # city 18 January, 2024

    # return 18 January, 2024

    # get the line from website_content which start with city
    lines = content.split('\n')
    for line in lines:
        if line.startswith(city):
            # get the date
            return line[len(city):].strip()

def upload_to_azure(
        city: str,
        earliest_date: str,
        email: str,
        tcn: bool,
        visa_type: str,
        group_id: str):
    table_name = conf.AZURE_TABLE_NAME
    table = service.get_table_client(table_name)
    entity = {
        'PartitionKey': visa_type,
        'RowKey': datetime.datetime.now(tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        'city': city,
        'available_date': earliest_date,
        'email': email,
        'tcn': tcn,
        'visa_type': visa_type,
        'group_id': group_id
    }
    table.upsert_entity(entity=entity)
    new_message = f'New appointment found for {visa_type} in {city} on {earliest_date}.'
    print(new_message)
    send_message(new_message)

def run_visa_scraper(no_appointment_text):
    # To run Chrome in a virtual display with xvfb (just in Linux)
    # display = Display(visible=0, size=(800, 600))
    # display.start()

    # randomize the time between checks to avoid being detected as a bot
    import random


    # Setting Chrome options to run the scraper headless.
    chrome_options = Options()
    # chrome_options.add_argument("--disable-extensions")
    # chrome_options.add_argument("--disable-gpu")
    # chrome_options.add_argument("--no-sandbox") # linux only
    if os.getenv('HEADLESS') == 'True':
        chrome_options.add_argument("--headless")  # Comment for visualy debugging

    # Initialize the chromediver (must be installed and in PATH)
    # Needed to implement the headless option

    for user, pwd, groupID, visa_type, tcn in get_next_account():
        print(f'Checking for {user}.')
        url = f'https://ais.usvisa-info.com/en-{COUNTRY_CODE}/niv/schedule/{groupID}/payment'
        seconds_between_checks = random.randint(15 * 60, 20 * 60)
        driver = webdriver.Chrome(options=chrome_options)
        current_time = time.strftime('%a, %d %b %Y %H:%M:%S', time.localtime())
        print(f'Starting a new check at {current_time}.')
        has_website_change, website_content = has_website_changed(driver, user, pwd, url, no_appointment_text)
        if has_website_change:
            print('A change was found. Notifying it.')

            countries = ['Calgary', 'Ottawa', 'Toronto', 'Vancouver', 'Halifax', 'Montreal', 'Quebec City']
            
            for country in countries:
                earliest_date = retrieve_earliest_date(website_content, country)
                if earliest_date:
                    upload_to_azure(
                        city=country,
                        earliest_date=earliest_date,
                        email=user,
                        tcn=tcn,
                        visa_type=visa_type,
                        group_id=groupID
                    )
            time.sleep(seconds_between_checks)
            driver.quit()
        else:
            # print(f'No change was found. Checking again in {seconds_between_checks} seconds.')
            # time.sleep(seconds_between_checks)
            send_message('you are blocked')
            continue
def main():
    text = 'There are no available appointments at this time.'

    # Checking for a rescheduled
    # url = base_url + '/appointment'
    # text = 'FORCING SCREENSHOT'
    # text = 'There are no available appointments at the selected location.'

    run_visa_scraper(text)


if __name__ == "__main__":
    main()
