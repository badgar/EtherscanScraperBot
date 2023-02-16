import re
import requests
import json
import telegram
import asyncio
import os
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import time
import blacklist
import api_keys

bot = telegram.Bot(token=f'{api_keys.telegram_token}')


def pick_random_user_agent():
    user_agent = UserAgent()
    header = {"user-agent": user_agent.random}
    return header


def get_explorer():
    header = pick_random_user_agent()
    print(f'Timestamp: {time.time()}')
    print(f'User agent: {header}')

    while True:
        try:
            response = requests.get(
                "https://etherscan.io/contractsVerified?ps=10",
                headers=header,
                timeout=15
            )
            if response.status_code == 200:
                return response.content
        except requests.exceptions as e:
            print(e)
            header = pick_random_user_agent()


def get_source_code(address):
    url = f'https://api.etherscan.io/api' \
          f'?module=contract' \
          f'&action=getsourcecode' \
          f'&address={address}' \
          f'&apikey={api_keys.etherscan_token}'
    r = requests.get(url)
    data = r.json()
    print(f'Requesting code for {address}')
    return data


def parse_response(response):
    scraped = []
    soup = BeautifulSoup(response, 'lxml')
    trs = soup.find_all('a', class_='js-clipboard')
    for tr in trs:
        address = tr['data-clipboard-text']
        scraped.append(address)
    return scraped


def contract_db(mode, scraped=None):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, 'scraped.json')
    if mode == 'w':
        with open(file_path, 'w') as outfile:
            json.dump(scraped, outfile)
    elif mode == 'r':
        try:
            with open(file_path, 'r') as infile:
                scraped = json.load(infile)
        except FileNotFoundError:
            with open(file_path, 'w') as outfile:
                json.dump([], outfile)
                scraped = []
        return scraped


def new_rows(old, new):
    old_set = set(old)
    new_set = set(new)
    new_contracts = list(new_set - old_set)
    print(f'Contracts found: {new_contracts}')
    return new_contracts


def extract_urls(text, suffix_set):
    url_pattern = re.compile(r'((?:(?:https?://)?(?:www\.)?)[\w.-]+\.[\w-]{2,}(?:/[\w\-.]*)?)')
    urls = re.findall(url_pattern, text)
    valid_urls = []
    for url in urls:
        if url.startswith(('https://', 'http://', 'www.')):
            valid_urls.append(url)
        else:
            domain_suffix = url.split('.')[-1]
            if domain_suffix in suffix_set:
                valid_urls.append(url)
    return valid_urls


async def check_source_for_url(contracts):
    with open('suffix.txt') as f:
        suffix_set = set(map(str.strip, f.readlines()))
    result = []
    for contract in contracts:
        website = []
        response = get_source_code(contract)
        print(f"Status: {response['status']}")
        contract_name = response['result'][0]['ContractName']
        src = response['result'][0]['SourceCode']
        if ('interface IERC20' in src) or ('interface ERC20' in src):
            src = src.split('interface')[0]
            urls = extract_urls(src, suffix_set)
            for url in urls:
                if not any(url.startswith(blacklisted) for blacklisted in blacklist.blacklist):
                    website.append(url)
            if website:
                found = {'contract': contract, 'name': contract_name, 'urls': website}
                result.append(found)
    return result


async def send_scraped_message():
    response = get_explorer()
    scraped_new = parse_response(response)

    scraped_old = contract_db('r')

    new_rows_list = new_rows(scraped_old, scraped_new)
    to_check = await check_source_for_url(new_rows_list)
    contract_db('w', scraped_new)

    message = ""
    for item in to_check:
        link = "https://etherscan.io/address/" + item['contract']
        name = item['name']
        message += "New contract: <a href='" + link + "'>" + name + "</a>\n"
        message += "Website: " + ", ".join(item['urls']) + "\n\n"
    if message:
        await bot.send_message(chat_id=f'{api_keys.telegram_chat_id}', text=message, parse_mode='HTML')


async def main():
    while True:
        await send_scraped_message()
        await asyncio.sleep(120)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
