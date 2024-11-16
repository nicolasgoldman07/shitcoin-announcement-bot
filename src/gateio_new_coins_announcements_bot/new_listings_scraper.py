import ast
import json
import os.path
import random
import re
import string
import time

import requests
from gate_api import ApiClient
from gate_api import SpotApi
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

import gateio_new_coins_announcements_bot.globals as globals
from gateio_new_coins_announcements_bot.auth.gateio_auth import load_gateio_creds
from gateio_new_coins_announcements_bot.load_config import load_config
from gateio_new_coins_announcements_bot.logger import logger
from gateio_new_coins_announcements_bot.store_order import load_order

config = load_config("config.yml")
client = load_gateio_creds("auth/auth.yml")
spot_api = SpotApi(ApiClient(client))

supported_currencies = None

previously_found_coins = set()


def get_binance_announcement():
    """
    Retrieves new coin listing announcements

    """
    logger.info("BINANCE - Pulling announcement page")

    random_number = random.randint(1, 99999999999999999999)
    random_string = "".join(random.choice(string.ascii_letters) for i in range(random.randint(10, 20)))
    request_url = (
        f"https://www.binance.com/en/support/announcement/new-cryptocurrency-listing?c=48"
        f"&rnd={random_number}"
        f"&{random_string}={random_number}"
    )

    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get(request_url)
    # TODO: Replace this with a more sophisticated wait
    time.sleep(5)

    listings = []
    try:
        articles = driver.find_elements(By.CSS_SELECTOR, "div.css-1yxx6id")
        for article in articles:
            title = article.text.strip()
            if title:
                listings.append({"title": title})

    finally:
        driver.quit()

    # filter the listings by to find the first one with "Will List"
    listings = [listing for listing in listings if "Will List" in listing["title"]]
    return listings[0]["title"]

    latest_announcement = requests.get(request_url)
    if latest_announcement.status_code == 200:
        try:
            logger.debug(f'X-Cache: {latest_announcement.headers["X-Cache"]}')
        except KeyError:
            # No X-Cache header was found - great news, we're hitting the source.
            pass

        latest_announcement = latest_announcement.json()
        logger.debug("Finished pulling announcement page")
        return latest_announcement["data"]["catalogs"][0]["articles"][0]["title"]
    else:
        logger.error(f"Error pulling binance announcement page: {latest_announcement.status_code}")
        return ""


def get_kucoin_announcement():
    """
    Retrieves new coin listing announcements from Kucoin

    """
    logger.info("KUCOIN - Pulling announcement page")
    # Generate random query/params to help prevent caching
    rand_page_size = random.randint(5, 10)
    letters = string.ascii_letters
    random_string = "".join(random.choice(letters) for i in range(random.randint(10, 20)))
    random_number = random.randint(1, 99999999999999999999)
    queries = [
        "page=1",
        f"pageSize={str(rand_page_size)}",
        "annType=new-listings",
        "lang=en_US",
        f"rnd={str(time.time())}",
        f"{random_string}={str(random_number)}",
    ]
    random.shuffle(queries)
    request_url = (
        f"https://api.kucoin.com/api/v3/announcements?"
        f"?{queries[0]}&{queries[1]}&{queries[2]}&{queries[3]}&{queries[4]}&{queries[5]}"
    )

    latest_announcement = requests.get(request_url)
    if latest_announcement.status_code == 200:
        try:
            logger.debug(f'X-Cache: {latest_announcement.headers["X-Cache"]}')
        except KeyError:
            # No X-Cache header was found - great news, we're hitting the source.
            pass

        latest_announcement = latest_announcement.json()
        filtered_announcements = list(
            filter(
                lambda announcement: set(announcement["annType"]) == {"latest-announcements", "new-listings"},
                latest_announcement["data"]["items"],
            )
        )

        if latest_announcement is None:
            logger.error("No announcements found")

        logger.info("Finished pulling announcement page")
        return filtered_announcements[0]["annTitle"]
    else:
        logger.error(f"Error pulling kucoin announcement page: {latest_announcement.status_code}")
        return ""


def get_binance_coin():
    """
    Checks for new Binance coin listings.
    Returns the new symbol if found, otherwise None.
    """
    if not config["TRADE_OPTIONS"]["BINANCE_ANNOUNCEMENTS"]:
        return None

    logger.info("Binance announcements enabled, looking for new Binance coins...")
    binance_announcement = get_binance_announcement()

    binance_coin = re.findall(r"\(([^)]+)", binance_announcement)

    if (
        "Will List" in binance_announcement
        and binance_coin
        and binance_coin[0] != globals.latest_listing
        and binance_coin[0] not in previously_found_coins
    ):
        # TODO: Add support of getting multi-coin announcements at the same time
        # TODO: Improve logic of always getting the first announcement coin
        coin = binance_coin[0]
        previously_found_coins.add(coin)
        logger.info(f"New previously found coins: {previously_found_coins}")
        logger.info(f"New Binance coin detected: {coin}")
        return coin

    return None


def get_kucoin_coin():
    """
    Checks for new Kucoin coin listings.
    Returns the new symbol if found, otherwise None.
    """
    if not config["TRADE_OPTIONS"]["KUCOIN_ANNOUNCEMENTS"]:
        return None

    # logger.info("Kucoin announcements enabled, looking for new Kucoin coins...")
    kucoin_announcement = get_kucoin_announcement()
    kucoin_coin = re.findall(r"\(([^)]+)", kucoin_announcement)

    if (
        "Gets Listed" in kucoin_announcement
        and kucoin_coin
        and kucoin_coin[0] != globals.latest_listing
        and kucoin_coin[0] not in previously_found_coins
    ):
        # TODO: Add support of getting multi-coin announcements at the same time
        # TODO: Improve logic of always getting the first announcement coin
        coin = kucoin_coin[0]
        previously_found_coins.add(coin)
        logger.info(f"New previously found coins: {previously_found_coins}")
        logger.info(f"New Kucoin coin detected: {coin}")
        return coin

    return None


# TODO: Add support of getting multi-exchange announcements at the same time
def get_last_coin():
    """
    Checks both Binance and Kucoin for new coin listings and returns the first found.
    Prioritizes Binance announcements over Kucoin.
    """
    binance_coin = get_binance_coin()
    if binance_coin:
        return binance_coin

    kucoin_coin = get_kucoin_coin()
    if kucoin_coin:
        return kucoin_coin

    return None


def store_new_listing(listing):
    """
    Only store a new listing if different from existing value
    """
    if listing and not listing == globals.latest_listing:
        logger.info("New listing detected")
        globals.latest_listing = listing
        globals.buy_ready.set()


def search_and_update():
    """
    Pretty much our main func
    """
    while not globals.stop_threads:
        sleep_time = 3
        for x in range(sleep_time):
            time.sleep(1)
            if globals.stop_threads:
                break
        try:
            latest_coin = get_last_coin()
            if latest_coin:
                store_new_listing(latest_coin)
            elif globals.test_mode and os.path.isfile("test_new_listing.json"):
                store_new_listing(load_order("test_new_listing.json"))
                if os.path.isfile("test_new_listing.json.used"):
                    os.remove("test_new_listing.json.used")
                os.rename("test_new_listing.json", "test_new_listing.json.used")
            logger.info(f"Checking for coin announcements every {str(sleep_time)} seconds (in a separate thread)")
        except Exception as e:
            logger.info(e)
    else:
        logger.info("while loop in search_and_update() has stopped.")


def get_all_currencies(single=False):
    """
    Get a list of all currencies supported on gate io
    :return:
    """
    global supported_currencies
    while not globals.stop_threads:
        logger.info("Getting the list of supported currencies from gate io")
        all_currencies = ast.literal_eval(str(spot_api.list_currencies()))
        currency_list = [currency["currency"] for currency in all_currencies]
        with open("currencies.json", "w") as f:
            json.dump(currency_list, f, indent=4)
            logger.info(
                "List of gate io currencies saved to currencies.json. Waiting 5 " "minutes before refreshing list..."
            )
        supported_currencies = currency_list
        if single:
            return supported_currencies
        else:
            for x in range(300):
                time.sleep(1)
                if globals.stop_threads:
                    break
    else:
        logger.info("while loop in get_all_currencies() has stopped.")


def load_old_coins():
    if os.path.isfile("old_coins.json"):
        with open("old_coins.json") as json_file:
            data = json.load(json_file)
            logger.info("Loaded old_coins from file")
            return data
    else:
        return []


def store_old_coins(old_coin_list):
    with open("old_coins.json", "w") as f:
        json.dump(old_coin_list, f, indent=2)
        logger.info("Wrote old_coins to file")
