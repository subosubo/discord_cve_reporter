import requests
import datetime
import pathlib
import json
import os
import yaml
import vulners
from os.path import join
from enum import Enum
from discord import Webhook, Embed, Color
import aiohttp, asyncio
from keep_alive import keep_alive
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging, sys

CIRCL_LU_URL = "https://cve.circl.lu/api/query"
CVES_JSON_PATH = join(
    pathlib.Path(__file__).parent.absolute(), "output/record.json")
LAST_NEW_CVE = datetime.datetime.now() - datetime.timedelta(days=1)
LAST_MODIFIED_CVE = datetime.datetime.now() - datetime.timedelta(days=1)
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

KEYWORDS_CONFIG_PATH = join(
    pathlib.Path(__file__).parent.absolute(), "config/config.yaml")
ALL_VALID = False
DESCRIPTION_KEYWORDS_I = []
DESCRIPTION_KEYWORDS = []
PRODUCT_KEYWORDS_I = []
PRODUCT_KEYWORDS = []


class Time_Type(Enum):
    PUBLISHED = "Published"
    LAST_MODIFIED = "last-modified"


logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='cve_reporter_discord.log',
                              encoding='utf-8',
                              mode='w')
handler.setFormatter(
    logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

################## LOAD CONFIGURATIONS ####################


def load_keywords():
    ''' Load keywords from config file '''

    global ALL_VALID
    global DESCRIPTION_KEYWORDS_I, DESCRIPTION_KEYWORDS
    global PRODUCT_KEYWORDS_I, PRODUCT_KEYWORDS
    try:

        with open(KEYWORDS_CONFIG_PATH, 'r') as yaml_file:
            keywords_config = yaml.safe_load(yaml_file)
            print(f"Loaded keywords: {keywords_config}")
            ALL_VALID = keywords_config["ALL_VALID"]
            DESCRIPTION_KEYWORDS_I = keywords_config["DESCRIPTION_KEYWORDS_I"]
            DESCRIPTION_KEYWORDS = keywords_config["DESCRIPTION_KEYWORDS"]
            PRODUCT_KEYWORDS_I = keywords_config["PRODUCT_KEYWORDS_I"]
            PRODUCT_KEYWORDS = keywords_config["PRODUCT_KEYWORDS"]

    except Exception as e:
        logger.error(e)
        sys.exit(1)


def load_lasttimes():
    ''' Load lasttimes from json file '''

    global LAST_NEW_CVE, LAST_MODIFIED_CVE

    try:
        with open(CVES_JSON_PATH, 'r') as json_file:
            cves_time = json.load(json_file)
            LAST_NEW_CVE = datetime.datetime.strptime(
                cves_time["LAST_NEW_CVE"], TIME_FORMAT)
            LAST_MODIFIED_CVE = datetime.datetime.strptime(
                cves_time["LAST_MODIFIED_CVE"], TIME_FORMAT)

    except Exception as e:  #If error, just keep the fault date (today - 1 day)
        print(f"ERROR, using default last times.\n{e}")
        logger.error(e)
        pass

    print(f"Last new cve: {LAST_NEW_CVE}")
    print(f"Last modified cve: {LAST_MODIFIED_CVE}")


def update_lasttimes():
    ''' Save lasttimes in json file '''

    with open(CVES_JSON_PATH, 'w') as json_file:
        json.dump(
            {
                "LAST_NEW_CVE": LAST_NEW_CVE.strftime(TIME_FORMAT),
                "LAST_MODIFIED_CVE": LAST_MODIFIED_CVE.strftime(TIME_FORMAT),
            }, json_file)


################## SEARCH CVES ####################


def get_cves(tt_filter: Time_Type) -> dict:
    ''' Given the headers for the API retrive CVEs from cve.circl.lu '''
    now = datetime.datetime.now() - datetime.timedelta(days=1)
    now_str = now.strftime("%d-%m-%Y")
    #https://cve.circl.lu/api/
    #time_modifier	Timeframe for the CVEs, related to the start and end time
    #time_start	Earliest time for a CVE
    #time_type	Select which time is used for the filter
    #limit	Limit the amount of vulnerabilities to return

    headers = {
        #"time_modifier": "from",
        #"time_start": now_str,
        "time_type": tt_filter.value,
        "limit": "100",
    }
    r = requests.get(CIRCL_LU_URL, headers=headers)

    return r.json()


def get_new_cves() -> list:
    ''' Get CVEs that are new '''

    global LAST_NEW_CVE

    cves = get_cves(Time_Type.PUBLISHED)
    filtered_cves, new_last_time = filter_cves(cves["results"], LAST_NEW_CVE,
                                               Time_Type.PUBLISHED)
    LAST_NEW_CVE = new_last_time

    return filtered_cves


def get_modified_cves() -> list:
    ''' Get CVEs that has been modified '''

    global LAST_MODIFIED_CVE

    cves = get_cves(Time_Type.LAST_MODIFIED)
    filtered_cves, new_last_time = filter_cves(cves["results"],
                                               LAST_MODIFIED_CVE,
                                               Time_Type.LAST_MODIFIED)
    LAST_MODIFIED_CVE = new_last_time

    return filtered_cves


def filter_cves(cves: list, last_time: datetime.datetime,
                tt_filter: Time_Type) -> list:
    ''' Filter by time the given list of CVEs '''

    filtered_cves = []
    new_last_time = last_time

    for cve in cves:
        cve_time = datetime.datetime.strptime(cve[tt_filter.value],
                                              TIME_FORMAT)
        if cve_time > last_time:
            if ALL_VALID or is_summ_keyword_present(cve["summary"]) or \
                is_prod_keyword_present(str(cve["vulnerable_configuration"])):

                filtered_cves.append(cve)

        if cve_time > new_last_time:
            new_last_time = cve_time

    return filtered_cves, new_last_time


def is_summ_keyword_present(summary: str):
    ''' Given the summary check if any keyword is present '''

    return any(w in summary for w in DESCRIPTION_KEYWORDS) or \
            any(w.lower() in summary.lower() for w in DESCRIPTION_KEYWORDS_I) #for each of the word in description keyword config, check if it exists in summary.


def is_prod_keyword_present(products: str):
    ''' Given the summary check if any keyword is present '''

    return any(w in products for w in PRODUCT_KEYWORDS) or \
            any(w.lower() in products.lower() for w in PRODUCT_KEYWORDS_I)


def search_exploits(cve: str) -> list:
    ''' Given a CVE it will search for public exploits to abuse it '''
    #use bot commands to find exploits for particular CVE
    return []

    vulners_api_key = os.getenv('VULNERS_API_KEY')

    if vulners_api_key:
        vulners_api = vulners.Vulners(api_key=vulners_api_key)
        cve_data = vulners_api.searchExploit(cve)
        return [v['vhref'] for v in cve_data]

    else:
        print("VULNERS_API_KEY wasn't configured in the secrets!")

    return []


#################### GENERATE MESSAGES #########################


def generate_new_cve_message(cve_data: dict) -> Embed:
    ''' Generate new CVE message for sending to slack '''

    nl = '\n'
    embed = Embed(
        title=f"🚨  *{cve_data['id']}*  🚨",
        description=cve_data["summary"] if len(cve_data["summary"]) < 500 else
        cve_data["summary"][:500] + "...",
        timestamp=datetime.datetime.utcnow(),
        color=Color.blue())
    if not cve_data["cvss"] == "None":
        embed.add_field(name=f"🔮  *CVSS*",
                        value=f"{cve_data['cvss']}",
                        inline=True)

    if not cve_data["cvss-vector"] == "None":
        embed.add_field(name=f"🔮  *CVSS Vector*",
                        value=f"{cve_data['cvss-vector']}",
                        inline=True)
    #else:
    #embed.add_field(name = f"🔮  *CVSS*", value = f"{cve_data['cvss']}/{cve_data['cvss-vector']}", inline = True)
    embed.add_field(name=f"📅  *Published*",
                    value=f"{cve_data['Published']}",
                    inline=True)
    if cve_data["vulnerable_configuration"]:
        embed.add_field(name=f"\n🔓  *Vulnerable* (_limit to 10_)",
                        value=f"{cve_data['vulnerable_configuration'][:10]}")
    embed.add_field(name=f"More Information (_limit to 5_)",
                    value=f"{nl.join(cve_data['references'][:5])}",
                    inline=False)

    return embed


def generate_modified_cve_message(cve_data: dict) -> Embed:
    ''' Generate modified CVE message for sending to slack '''

    embed = Embed(
        title=f"📣 *{cve_data['id']} Modified*",
        description=
        f"*{cve_data['id']}*(_{cve_data['cvss']}_) was modified on {cve_data['last-modified'].split('T')[0]}",
        timestamp=datetime.datetime.utcnow(),
        color=Color.gold())

    embed.add_field(name=f"🗣 *Summary*",
                    value=cve_data["summary"] if len(cve_data["summary"]) < 500
                    else cve_data["summary"][:500] + "...",
                    inline=False)

    if not cve_data["cvss"] == "None":
        embed.add_field(name=f"🔮  *CVSS*",
                        value=f"{cve_data['cvss']}",
                        inline=True)

    if not cve_data["cvss-vector"] == "None":
        embed.add_field(name=f"🔮  *CVSS Vector*",
                        value=f"{cve_data['cvss-vector']}",
                        inline=True)

    embed.set_footer(
        text=f"(First published on {cve_data['Published'].split('T')[0]})\n")

    return embed


def generate_public_expls_message(public_expls: list) -> Embed:
    ''' Given the list of public exploits, generate the message '''

    embed = Embed(title=f"**Public Exploits located**",
                  timestamp=datetime.datetime.utcnow(),
                  color=Color.red())
    embed.add_field(name=f"More Information (_limit to 20_)",
                    value=f"{public_expls[:20]}",
                    inline=False)
    return embed


#################### SEND MESSAGES #########################


def send_slack_mesage(message: str, public_expls_msg: str):
    ''' Send a message to the slack group '''

    slack_url = os.getenv('SLACK_WEBHOOK')

    if not slack_url:
        print("SLACK_WEBHOOK wasn't configured in the secrets!")
        return

    json_params = {
        "blocks": [{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": message
            }
        }, {
            "type": "divider"
        }]
    }

    if public_expls_msg:
        json_params["blocks"].append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": public_expls_msg
            }
        })

    requests.post(slack_url, json=json_params)


def send_telegram_message(message: str, public_expls_msg: str):
    ''' Send a message to the telegram group '''

    telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if not telegram_bot_token:
        print("TELEGRAM_BOT_TOKEN wasn't configured in the secrets!")
        return

    if not telegram_chat_id:
        print("TELEGRAM_CHAT_ID wasn't configured in the secrets!")
        return

    if public_expls_msg:
        message = message + "\n" + public_expls_msg

    message = message.replace(".", "\.").replace("-", "\-").replace(
        "(",
        "\(").replace(")", "\)").replace("_", "").replace("[", "\[").replace(
            "]", "\]").replace("{", "\{").replace("}",
                                                  "\}").replace("=", "\=")
    r = requests.get(
        f'https://api.telegram.org/bot{telegram_bot_token}/sendMessage?parse_mode=MarkdownV2&text={message}&chat_id={telegram_chat_id}'
    )

    resp = r.json()
    if not resp['ok']:
        r = requests.get(
            f'https://api.telegram.org/bot{telegram_bot_token}/sendMessage?parse_mode=MarkdownV2&text=Error with'
            + message.split("\n")[0] +
            f'{resp["description"]}&chat_id={telegram_chat_id}')
        resp = r.json()
        if not resp['ok']:
            print("ERROR SENDING TO TELEGRAM: " + message.split("\n")[0] +
                  resp["description"])


async def send_discord_message(message: Embed, public_expls_msg: str):
    ''' Send a message to the discord channel webhook '''

    discord_webhok_url = os.getenv('DISCORD_WEBHOOK_URL')

    if not discord_webhok_url:
        print("DISCORD_WEBHOOK_URL wasn't configured in the secrets!")
        return

    await sendtoWebhook(WebHookURL=discord_webhok_url, content=message)


async def sendtoWebhook(WebHookURL: str, content: Embed):
    async with aiohttp.ClientSession() as session:
        webhook = Webhook.from_url(WebHookURL, session=session)
        await webhook.send(embed=content)


#################### CHECKING for CVE #########################


async def itscheckintime():

    try:
        #Load configured keywords
        load_keywords()

        #Start loading time of last checked ones
        load_lasttimes()

        #Find a publish new CVEs
        new_cves = get_new_cves()

        new_cves_ids = [ncve['id'] for ncve in new_cves]
        print(f"New CVEs discovered: {new_cves_ids}")

        for new_cve in new_cves:
            public_exploits = search_exploits(new_cve['id'])
            cve_message = generate_new_cve_message(new_cve)
            public_expls_msg = generate_public_expls_message(public_exploits)
            #send_slack_mesage(cve_message, public_expls_msg)
            #send_telegram_message(cve_message, public_expls_msg)
            await send_discord_message(cve_message, public_expls_msg)

        #Find and publish modified CVEs
        modified_cves = get_modified_cves()

        modified_cves = [
            mcve for mcve in modified_cves if not mcve['id'] in new_cves_ids
        ]
        modified_cves_ids = [mcve['id'] for mcve in modified_cves]
        print(f"Modified CVEs discovered: {modified_cves_ids}")

        for modified_cve in modified_cves:
            public_exploits = search_exploits(modified_cve['id'])
            cve_message = generate_modified_cve_message(modified_cve)
            public_expls_msg = generate_public_expls_message(public_exploits)
            #send_slack_mesage(cve_message, public_expls_msg)
            #send_telegram_message(cve_message, public_expls_msg)
            await send_discord_message(cve_message, public_expls_msg)

        #Update last times
        update_lasttimes()

    except Exception as e:
        logger.error(e)
        sys.exit(1)


#################### MAIN #########################
if __name__ == "__main__":
    keep_alive()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(itscheckintime, 'interval', minutes=5)
    scheduler.start()
    print('Press Ctrl+{0} to exit'.format('Break' if os.name == 'nt' else 'C'))

    # Execution will block here until Ctrl+C (Ctrl+Break on Windows) is pressed.
    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
