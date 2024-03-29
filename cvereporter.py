from enum import Enum
from os.path import join
from discord import Color, Embed
import datetime
import json
import logging
import pathlib
import sys
import pytz
import requests
import yaml
import re

utc = pytz.UTC


class time_type(Enum):
    PUBLISHED = "Published"
    LAST_MODIFIED = "last-modified"


class cvereport:
    def __init__(self):

        self.CIRCL_LU_URL = "https://cve.circl.lu/api/query"
        self.CVES_JSON_PATH = join(
            pathlib.Path(__file__).parent.absolute(), "output/record.json"
        )
        self.LAST_NEW_CVE = datetime.datetime.now(
            utc) - datetime.timedelta(days=1)
        self.LAST_MODIFIED_CVE = datetime.datetime.now(
            utc) - datetime.timedelta(days=1)
        self.TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
        self.logger = logging.getLogger("__main__")
        self.logger.setLevel(logging.INFO)

        self.new_cves = []
        self.mod_cves = []
        self.new_cves_ids = []
        self.modified_cves_ids = []

        # Load keywords from config file

        self.KEYWORDS_CONFIG_PATH = join(
            pathlib.Path(__file__).parent.absolute(), "config/config.yaml"
        )
        try:

            with open(self.KEYWORDS_CONFIG_PATH, "r") as yaml_file:
                keywords_config = yaml.safe_load(yaml_file)
                self.logger.info(f"Loaded keywords: {keywords_config}")
                self.valid = keywords_config['ALL_VALID']
                self.keywords_i = [
                    key.lower() for key in keywords_config['DESCRIPTION_KEYWORDS_I']]
                self.keywords = keywords_config['DESCRIPTION_KEYWORDS']
                self.product_i = [
                    prod.lower() for prod in keywords_config['PRODUCT_KEYWORDS_I']]
                self.product = keywords_config['PRODUCT_KEYWORDS']
            yaml_file.close()
        except Exception as e:
            self.logger.error(e)
            sys.exit(1)

    ################## LOAD CONFIGURATIONS ####################

    def load_lasttimes(self):
        # Load lasttimes from json file

        try:
            with open(self.CVES_JSON_PATH, "r") as json_file:
                cves_time = json.load(json_file)
                self.LAST_NEW_CVE = datetime.datetime.strptime(
                    cves_time['LAST_NEW_CVE'], self.TIME_FORMAT
                )
                self.LAST_MODIFIED_CVE = datetime.datetime.strptime(
                    cves_time['LAST_MODIFIED_CVE'], self.TIME_FORMAT
                )
            json_file.close()
        # If error, just keep the fault date (today - 1 day)
        except Exception as e:
            self.logger.error(f"ERROR - using default last times.\n{e}")

        self.logger.info(f"Last new cve: {self.LAST_NEW_CVE}")
        self.logger.info(f"Last modified cve: {self.LAST_MODIFIED_CVE}")

    def update_lasttimes(self):
        # Save lasttimes in json file
        try:
            with open(self.CVES_JSON_PATH, "w") as json_file:
                json.dump(
                    {
                        "LAST_NEW_CVE": self.LAST_NEW_CVE.strftime(self.TIME_FORMAT),
                        "LAST_MODIFIED_CVE": self.LAST_MODIFIED_CVE.strftime(
                            self.TIME_FORMAT
                        ),
                    },
                    json_file,
                )
            json_file.close()
        except Exception as e:
            self.logger.error(f"ERROR: {e}")

    ################## SEARCH CVES ####################

    def remove_duplicate(self, orig_list: list) -> list:
        uniq_list = [i for n, i in enumerate(
            orig_list) if i not in orig_list[n + 1:]]

        return uniq_list

    def request_cves(self, tt_filter: time_type) -> dict:
        # Given the headers for the API retrive CVEs from cve.circl.lu
        now = datetime.datetime.now() - datetime.timedelta(days=1)
        now_str = now.strftime("%d-%m-%Y")
        # https://cve.circl.lu/api/
        # time_modifier	Timeframe for the CVEs, related to the start and end time
        # time_start	Earliest time for a CVE
        # time_type	Select which time is used for the filter
        # limit	Limit the amount of vulnerabilities to return

        headers = {
            "time_modifier": "from",
            "time_start": now_str,
            "time_type": tt_filter.value,
            "limit": "100",
        }
        r = requests.get(self.CIRCL_LU_URL, headers=headers)

        return r.json()

    def get_new_cves(self):
        # Get CVEs that are new#

        cves = self.request_cves(time_type.PUBLISHED)
        self.new_cves, self.LAST_NEW_CVE = self.filter_cves(
            cves['results'], self.LAST_NEW_CVE, time_type.PUBLISHED
        )

        self.new_cves_ids = [ncve['id'] for ncve in self.new_cves]
        self.logger.info(f"New CVEs discovered: {self.new_cves_ids}")

    def get_modified_cves(self) -> list:
        # Get CVEs that has been modified

        cves = self.request_cves(time_type.LAST_MODIFIED)
        modified_cves, self.LAST_MODIFIED_CVE = self.filter_cves(
            cves['results'], self.LAST_MODIFIED_CVE, time_type.LAST_MODIFIED
        )

        # only displays modified cves that is not the same as new_cve_id and
        self.mod_cves = [
            mcve for mcve in modified_cves if mcve['id'] not in self.new_cves_ids
        ]

        self.modified_cves_ids = [mcve['id'] for mcve in self.mod_cves]
        self.logger.info(f"Modified CVEs discovered: {self.modified_cves_ids}")

    def filter_cves(
        self, cves: list, last_time: datetime.datetime, tt_filter: time_type
    ):
        # Filter by time the given list of CVEs

        filtered_cves = []
        new_last_time = last_time

        for cve in cves:
            # if report has no references, skip to next report
            if not cve['references']:
                continue

            cve_time = datetime.datetime.strptime(
                cve[tt_filter.value], self.TIME_FORMAT
            )

            # list.extend from both functions
            match_keyword, match_keyword_prod = [], []

            match_keyword = self.is_summ_keyword_present(cve['summary'])
            match_keyword_prod = self.is_prod_keyword_present(
                str(cve['vulnerable_configuration']))
            match_keyword.extend(match_keyword_prod)

            unique_list = self.remove_duplicate(match_keyword)
            print(unique_list)

            # last_time is from config
            # cve time is api data
            # caters to multiple new cves with same published/modified timev
            if cve_time > last_time and (self.valid or unique_list):
                cve['keywords'] = unique_list
                filtered_cves.append(cve)

            if cve_time > new_last_time:
                new_last_time = cve_time

        return filtered_cves, new_last_time

    def is_summ_keyword_present(self, summary: str):
        # Given the summary check if any keyword is present
        # '\b' is a word boundary, which ensures that the keyword is matched only when it appears as a whole word.
        # Parenthese around the keywords in the pattern is a capturing group which will return the exact matched word instead of the match with | in it.
        # re.search instead of
        try:
            pattern_i = re.compile(
                r"\b(" + "|".join(self.keywords_i) + r")\b")
            matches_i = pattern_i.finditer(summary.lower())
            match_words_i = [match.group() for match in matches_i]

            pattern = re.compile(r"\b(" + "|".join(self.keywords) + r")\b")
            matches = pattern.finditer(summary)
            match_words = [match.group() for match in matches]

            match_words_i.extend(match_words)
            match_words_i = self.remove_duplicate(match_words_i)

            return match_words_i

        except Exception as e:
            self.logger.error(e)

    def is_prod_keyword_present(self, products: str):
        # Given the summary check if any keyword is present
        try:
            pattern_i = re.compile(
                r"\b(" + "|".join(self.product_i) + r")\b")
            matches_i = pattern_i.finditer(products.lower())
            match_words_i = [match.group() for match in matches_i]

            pattern = re.compile(r"\b(" + "|".join(self.product) + r")\b")
            matches = pattern.finditer(products)
            match_words = [match.group() for match in matches]

            match_words_i.extend(match_words)
            match_words_i = self.remove_duplicate(match_words_i)

            return match_words_i

        except Exception as e:
            self.logger.error(e)

    def search_exploits(self, cve: str) -> list:
        # Given a CVE it will search for public exploits to abuse it
        # use bot commands to find exploits for particular CVE

        # return blank because basic vulner user has limited search hence removing exploit search function, but source code works
        return []

        # vulners_api_key = os.getenv("VULNERS_API_KEY")

        # if vulners_api_key:
        #     vulners_api = vulners.VulnersApi(api_key=vulners_api_key)
        #     cve_data = vulners_api.find_exploit_all(cve)
        #     return [v['vhref'] for v in cve_data]

        # else:
        #     print("VULNERS_API_KEY wasn't configured in the secrets!")

        # return []

    #################### GENERATE MESSAGES #########################

    def generate_new_cve_message(self, cve_data: dict) -> Embed:
        # Generate new CVE message for sending to discord

        nl = "\n"
        embed = Embed(
            title=f"🚨  *{cve_data['id']}*  🚨",
            description=cve_data['summary'] if len(
                cve_data['summary']) < 400 else cve_data['summary'][:400] + "...",
            timestamp=datetime.datetime.now(),
            color=Color.blue(),
        )
        try:
            if cve_data['keywords']:
                keyw = ", ".join(str(x) for x in cve_data['keywords'])
                embed.add_field(name=f"✅  *Keywords*",
                                value=f"{keyw}", inline=True)
        except KeyError:
            pass

        # if cve_data['cvss'] != "None":
        #     embed.add_field(name=f"🔮  *CVSS*",
        #                     value=f"{cve_data['cvss']}", inline=True)

        embed.add_field(
            name=f"📅  *Published*", value=f"{cve_data['Published']}", inline=True
        )

        if cve_data['vulnerable_configuration']:
            embed.add_field(
                name=f"🔓  *Vulnerable* (_limit to 6_)",
                value=f"{nl.join(cve_data['vulnerable_configuration'][:6])}",
                inline=False,
            )

        embed.add_field(
            name=f"More Information (_limit to 4_)",
            value=f"{nl.join(cve_data['references'][:4])}",
            inline=False,
        )

        return embed

    def generate_modified_cve_message(self, cve_data: dict) -> Embed:
        # Generate modified CVE message for sending to discord
        # description=f"*{cve_data['id']}*(_{cve_data['cvss']}_) was modified on {cve_data['last-modified'].split('T')[0]}",
        descript = ""
        nl = "\n"
        if "cvss-vector" in cve_data and cve_data['cvss-vector'] != "None" and "cvss" in cve_data and cve_data['cvss'] != "None":
            descript = f"CVSS: {cve_data['cvss-vector']} ({cve_data['cvss']}){nl}"
        if "cwe" in cve_data and cve_data['cwe'] != "None":
            descript += f"CWE: {cve_data['cwe']}"

        embed = Embed(
            title=f"📣 *{cve_data['id']} Modified*",
            description=descript,
            timestamp=datetime.datetime.now(),
            color=Color.gold(),
        )

        embed.add_field(name=f"🗣 *Summary*", value=cve_data['summary'] if len(
            cve_data['summary']) < 400 else cve_data['summary'][:400] + "...", inline=False,)

        try:
            if cve_data['keywords']:
                print(f"{cve_data['id']}")
                print(f"{cve_data['keywords']}")
                keyw = ", ".join(str(x) for x in cve_data['keywords'])
                embed.add_field(name=f"✅  *Keywords*",
                                value=f"{keyw}", inline=True)
        except KeyError:
            pass

        embed.add_field(name=f"📅  *Modified*",
                        value=f"{cve_data['last-modified']}", inline=True)

        embed.add_field(
            name=f"More Information (_limit to 4_)",
            value=f"{nl.join(cve_data['references'][:4])}",
            inline=False,
        )

        embed.set_footer(
            text=f"(First published on {cve_data['Published'].split('T')[0]})\n"
        )

        return embed

    def generate_public_expls_message(self, public_expls: list) -> str:
        # Given the list of public exploits, generate the message

        message = ""
        nl = "\n"

        if public_expls:
            message = f"{nl.join(public_expls[:10])}"

        return message
