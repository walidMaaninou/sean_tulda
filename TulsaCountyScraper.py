import streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
import time
import json
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta

# Function to log messages with icons in a single text area
def log_message(msg, icon="📝"):
    st.session_state["logs"].append(f"{icon} {msg}")
    st.session_state["logs"] = st.session_state["logs"][-10:]
    log_text = "\n".join(st.session_state["logs"])
    log_area.text_area("Logs", log_text, height=260)

# Initialize session state for logs and data
if "logs" not in st.session_state:
    st.session_state["logs"] = []
if "updated_data" not in st.session_state:
    st.session_state["updated_data"] = []

# Streamlit app title
st.title("Tulsa County Scraper")

# Disable the button when clicked
if "scraper_initialized" not in st.session_state:
    st.session_state.scraper_initialized = False

# Create a placeholder for logs
log_area = st.empty()

# Placeholder for the progress bar
progress_bar = st.progress(0)
progress_text = st.empty()

# Create a dynamic table placeholder for updated data
data_table = st.empty()

# Button to initialize the scraper
initialize_button = st.button("Initialize the Scraper", disabled=st.session_state.scraper_initialized)

if initialize_button:
    st.session_state.scraper_initialized = True
    with st.spinner("Initializing scraper... Please wait."):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

        # service = Service(ChromeDriverManager(driver_version="120.0.6099.224").install())
        service = Service(ChromeDriverManager(driver_version="134.0.6998.89").install())

        driver = webdriver.Chrome(service=service, options=chrome_options)

        driver.get("https://acclaim.tulsacounty.org/AcclaimWeb/Account/Login")
        wait = WebDriverWait(driver, 10)

        username_field = wait.until(EC.presence_of_element_located((By.ID, "Username")))
        username_field.send_keys("sean@rpoproperties.com")
        password_field = wait.until(EC.presence_of_element_located((By.ID, "Password")))
        password_field.send_keys("Jackson2014")
        login_button = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "loginButton")))
        login_button.click()

        img_element = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//img[@alt='Date Range/Document Type']"))
        )
        img_element.click()

        select_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "DocTypesList"))
        )

        options = select_element.find_elements(By.TAG_NAME, "option")
        options_list = [option.get_attribute("innerHTML") for option in options]

        st.session_state["options"] = options_list
        st.session_state["driver"] = driver
    st.success("Scraper initialized! Select your options below.")

# Display dropdowns if options exist
if "options" in st.session_state:
    selected_options = st.multiselect("Select document types:", st.session_state["options"])
    
    # Add date range selection dropdown
    date_range_options = ["1 Year", "3 Months"]
    selected_date_range = st.selectbox("Select date range:", date_range_options)

    # Start scraping button
    if st.button("Start Scraping"):
        driver = st.session_state["driver"]
        driver.refresh()
        wait = WebDriverWait(driver, 10)

        # Calculate dates based on selection
        if selected_date_range == "1 Year":
            days_back = 365
        else:  # 3 Months
            days_back = 90
            
        start_date = (datetime.today() - timedelta(days=days_back)).strftime("%m%d%Y")
        today = datetime.today().strftime("%m%d%Y")

        from_date = driver.find_element(By.ID, "FromDatePicker")
        from_date.clear()
        for i in range(10):
            from_date.send_keys(Keys.ARROW_LEFT)
        from_date.send_keys(start_date)

        to_date = driver.find_element(By.ID, "ToDatePicker")
        to_date.clear()
        for i in range(10):
            to_date.send_keys(Keys.ARROW_LEFT)
        to_date.send_keys(today)

        input_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input.k-input.k-readonly")))
        for select_option in selected_options:
            input_element.send_keys(select_option)
            time.sleep(0.5)
            input_element.send_keys(Keys.RETURN)
            time.sleep(0.5)

        search_button = wait.until(EC.element_to_be_clickable((By.ID, "SearchBtn")))
        search_button.click()
        try:
            time.sleep(1)
            search_button.click()
        except:
            pass

        log_message("Search initiated, waiting for results...", "⏳")
        time.sleep(5)

        log_message("Fetching network logs...", "🔄")
        def process_browser_log_entry(entry):
            response = json.loads(entry['message'])['message']
            return response

        browser_log = driver.get_log('performance')
        events = [process_browser_log_entry(entry) for entry in browser_log]
        events = [event for event in events if 'Network.response' in event['method']]

        searchRequest = None
        for event in events:
            try:
                if "/GetSearchResults" in event["params"]["response"]["url"]:
                    searchRequest = event["params"]["requestId"]
                    log_message(f"Found request: {event['params']['response']['url']}", "🔍")
            except:
                pass

        if searchRequest:
            response = driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': searchRequest})
            data = json.loads(response["body"])

            total_results = len(data["Data"])
            results_with_assessor_link = sum(1 for item in data["Data"] if item.get("ParcelNumber") is not None)

            log_message(f"Total elements found: {total_results}", "📊")
            log_message(f"Elements with assessor link (non-null ParcelNumber): {results_with_assessor_link}", "📑")

            total_count = len(data["Data"])
            for index, item in enumerate(data["Data"]):
                parcel_number = item.get("ParcelNumber")
                if parcel_number:
                    url = f"https://assessor.tulsacounty.org/Property/Info?accountNo=R{parcel_number}"
                    log_message(f"Fetching data for ParcelNumber: {parcel_number}", "🔗")

                    r = requests.get(url)
                    soup = BeautifulSoup(r.text, "html.parser")

                    table = soup.select_one("#propertyInfoTabs-content table")
                    row_data = {}

                    if table:
                        for row in table.find_all("tr"):
                            header = row.find("th")
                            value = row.find("td")
                            if header and value:
                                key = header.get_text(strip=True)
                                val = value.get_text(" ", strip=True)
                                row_data[key] = val
                    
                    item.update(row_data)
                    st.session_state["updated_data"].append(item)

                progress = (index + 1) / total_count
                progress_bar.progress(progress)
                progress_text.text(f"Progress: {int(progress * 100)}%")

                dynamic_df = pd.DataFrame(st.session_state["updated_data"])
                data_table.dataframe(dynamic_df)

            log_message("Displaying updated results...", "✅")
            st.dataframe(st.session_state["updated_data"])
        else:
            log_message("No search results found.", "⚠️")