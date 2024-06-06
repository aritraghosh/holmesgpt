import base64
import json
import logging
import os
from typing import Dict, Optional, List

import yaml
from supabase import create_client
from supabase.lib.client_options import ClientOptions
from pydantic import BaseModel

from holmes.common.env_vars import (ROBUSTA_CONFIG_PATH, ROBUSTA_ACCOUNT_ID, STORE_URL, STORE_API_KEY, STORE_EMAIL,
                                    STORE_PASSWORD)


SUPABASE_TIMEOUT_SECONDS = int(os.getenv("SUPABASE_TIMEOUT_SECONDS", 3600))

ISSUES_TABLE = "Issues"
EVIDENCE_TABLE = "Evidence"


class RobustaConfig(BaseModel):
    sinks_config: List[Dict[str, Dict]]


class RobustaToken(BaseModel):
    store_url: str
    api_key: str
    account_id: str
    email: str
    password: str


class SupabaseDal:

    def __init__(self):
        self.enabled = self.__init_config()
        if not self.enabled:
            logging.info("Robusta store initialization parameters not provided. skipping")
            return
        logging.info(f"Initializing robusta store for account {self.account_id}")
        options = ClientOptions(postgrest_client_timeout=SUPABASE_TIMEOUT_SECONDS)
        self.client = create_client(self.url, self.api_key, options)
        self.sign_in()

    @staticmethod
    def __load_robusta_config() -> Optional[RobustaToken]:
        config_file_path = ROBUSTA_CONFIG_PATH
        if not os.path.exists(config_file_path):
            logging.info(f"No robusta config in {config_file_path}")
            return None

        logging.info(f"loading config {config_file_path}")
        with open(config_file_path) as file:
            yaml_content = yaml.safe_load(file)
            config = RobustaConfig(**yaml_content)
            for conf in config.sinks_config:
                if "robusta_sink" in conf.keys():
                    token = conf["robusta_sink"].get("token")
                    return RobustaToken(**json.loads(base64.b64decode(token)))

        return None

    def __init_config(self) -> bool:
        robusta_token = self.__load_robusta_config()
        if robusta_token:
            self.account_id = robusta_token.account_id
            self.url = robusta_token.store_url
            self.api_key = robusta_token.api_key
            self.email = robusta_token.email
            self.password = robusta_token.password
        else:
            self.account_id = ROBUSTA_ACCOUNT_ID
            self.url = STORE_URL
            self.api_key = STORE_API_KEY
            self.email = STORE_EMAIL
            self.password = STORE_PASSWORD

        # valid only if all store parameters are provided
        return all([self.account_id, self.url, self.api_key, self.email, self.password])

    def sign_in(self):
        logging.info("Supabase DAL login")
        res = self.client.auth.sign_in_with_password({"email": self.email, "password": self.password})
        self.client.auth.set_session(res.session.access_token, res.session.refresh_token)
        self.client.postgrest.auth(res.session.access_token)

    def get_issue_data(self, issue_id: str) -> Optional[Dict]:
        # TODO this could be done in a single atomic SELECT, but there is no
        # foreign key relation between Issues and Evidence.

        if not self.enabled:  # store not initialized
            return None
        issue_data = None
        try:
            issue_response = (
                self.client
                    .table(ISSUES_TABLE)
                    .select(f"*")
                    .filter("id", "eq", issue_id)
                    .execute()
            )
            if len(issue_response.data):
                issue_data = issue_response.data[0]

        except:  # e.g. invalid id format
            logging.exception("Supabase error while retrieving issue data")
            return None
        if not issue_data:
            return None
        evidence = (
            self.client
            .table(EVIDENCE_TABLE)
            .select(f"*")
            .filter("issue_id", "eq", issue_id)
            .execute()
        )
        issue_data["evidence"] = evidence.data
        return issue_data
