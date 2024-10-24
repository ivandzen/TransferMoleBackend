import logging
import json
from psycopg2.extensions import cursor
from typing import ClassVar, Dict
import copy

from .country import Country
from .common.api_error import APIError
from .advanced_form import AdvancedForm


DEFAULT_INDIVIDUAL_REQS = {
    "fields": {
        "first_name": {
            "label": "First name",
            "type": "text-input",
            "required": True
        },
        "last_name": {
            "label": "Last name",
            "type": "text-input",
            "required": True
        },
        "dob": {
            "label": "Date of birth",
            "type": "date",
            "required": True
        },
        "email": {
            "label": "e-mail",
            "type": "text-input",
            "required": True,
            "params": {
                "regexp": "^\\w+([\\.-]?\\w+)*@\\w+([\\.-]?\\w+)*(\\.\\w{2,3})+$"
            }
        },
        "phone": {
            "label": "Phone",
            "type": "phone",
            "required": True,
            "params": {
                "defaultCountry": "sg"
            }
        },
        "address": {
            "label": "Address",
            "type": "object",
            "required": True,
            "params": {
                "children": {
                    "state": {
                        "label": "State/Region",
                        "type": "text-input",
                        "required": False,
                        "helperText": "Enter state or local region"
                    },
                    "city": {
                        "label": "City",
                        "type": "text-input",
                        "required": True,
                        "helperText": "Enter city name"
                    },
                    "line1": {
                        "label": "Address line 1",
                        "type": "text-input",
                        "required": True
                    },
                    "line2": {
                        "label": "Address line 2",
                        "type": "text-input",
                        "required": True
                    },
                    "postal_code": {
                        "label": "Postal Code",
                        "type": "text-input",
                        "required": True
                    }
                }
            }
        },
        "id_number": {
            "label": "ID document number",
            "type": "text-input",
            "required": True
        },
    },
    "objects": {}
}


logger = logging.getLogger(__name__)


class CountryCache:
    COUNTRY_CACHE: ClassVar[Dict[str, Country]] = {}
    COUNTRY_BY_CODE: ClassVar[Dict[str, Country]] = {}

    @staticmethod
    def update_cache(cur: cursor) -> None:
        logger.info("Updating Country cache...")
        cur.execute(
            f"SELECT c.name, c.code, c.bank_account_requirements, c.individual_requirements, "
            f"c.kyc_provider, c.payout_providers "
            f"FROM public.country AS c;"
        )
        for country in cur:
            bank_account_requirements = AdvancedForm.model_validate(json.loads(country[2])) if country[2] else None
            if country[3]:
                individual_requirements = json.loads(country[3])
            else:
                individual_requirements = copy.deepcopy(DEFAULT_INDIVIDUAL_REQS)
                individual_requirements["fields"]["phone"]["params"]["defaultCountry"] = country[1].lower()

            obj = Country(
                name=country[0], code=country[1],
                bank_account_requirements=bank_account_requirements,
                individual_requirements=AdvancedForm.model_validate(individual_requirements),
                payout_providers=country[5],
                kyc_providers=[country[4]] if country[4] else [],
            )

            CountryCache.COUNTRY_CACHE[country[0]] = obj
            CountryCache.COUNTRY_BY_CODE[country[1]] = obj

        logger.info(f"Total {len(CountryCache.COUNTRY_CACHE)} countries preloaded.")

    @staticmethod
    def get_country(country_name: str | None) -> 'Country':
        if country_name is None:
            raise APIError(APIError.INTERNAL, "Country not set")

        country = CountryCache.COUNTRY_CACHE.get(country_name, None)
        if country is None:
            raise APIError(APIError.OBJECT_NOT_FOUND, f"Country {country_name} not supported")
        return country

    @staticmethod
    def get_country_by_code(code: str) -> 'Country':
        country = CountryCache.COUNTRY_BY_CODE.get(code, None)
        if country is None:
            raise APIError(APIError.OBJECT_NOT_FOUND, f"Country {code} not found")
        return country
