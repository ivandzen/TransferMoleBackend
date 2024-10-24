from typing import Union, Dict, List, Literal, Annotated, Optional, Any

import pydantic
from pydantic import BaseModel, Field
import re
import logging

from .common.api_error import APIError
from .country_codes import country_codes


logger = logging.getLogger(__name__)


class DateValue(BaseModel):
    year: Optional[int] = Field(None, ge=0)
    month: Optional[int] = Field(None, ge=1, le=12)
    day: Optional[int] = Field(None, ge=1, le=31)


class TextInputParams(BaseModel):
    regexp: str


class ObjectOptions(BaseModel):
    objectSetName: str
    filterCondition: Optional[str] = Field(default=None)


class SelectBoxParams(BaseModel):
    strOptions: Optional[list[str]] = Field(default=None)
    objOptions: Optional[ObjectOptions] = Field(default=None)


class PhoneInputParams(BaseModel):
    defaultCountry: str


ObjectCollection = Dict[str, List[Dict[Any, Any]]]


class BaseFieldSettings(BaseModel):
    label: str
    required: Optional[bool] = Field(default=None)
    helperText: Optional[str] = Field(default=None)

    def check_value(self, form_data: dict, field_name: str, objects: Optional[ObjectCollection], soft_mode: bool) -> Any:
        field_value = form_data.get(field_name, None)
        if not soft_mode:
            if self.required and not field_value:
                raise APIError(
                    APIError.FORM_DATA,
                    f"Value for field {field_name} is required"
                )

        if field_value:
            return self.detailed_check_value(field_name, field_value, objects, form_data, soft_mode)

        return field_value

    def detailed_check_value(
            self, field_name: str, value: Any, _objects: Optional[ObjectCollection], form_data: dict, soft_mode: bool
    ) -> Any:
        raise APIError(APIError.INTERNAL, f"{self.label} : BaseFieldSettings.detailed_check_value")

    def raise_error(self, field_name: str) -> None:
        raise APIError(
            APIError.FORM_DATA,
            f"{field_name} - incorrect value. {self.helperText if self.helperText else ''}"
        )


class TextInputSettings(BaseFieldSettings):
    type: Literal["text-input"]
    params: TextInputParams | None = Field(default=None)

    def detailed_check_value(
            self, field_name: str, value: str, objects: Optional[ObjectCollection], form_data: dict, soft_mode: bool
    ) -> Any:
        if self.params and self.params.regexp:
            regexp = re.compile(self.params.regexp)
            if not regexp.match(value):
                if not soft_mode:
                    self.raise_error(field_name)
                else:
                    return None

        return value


class SelectBoxSettings(BaseFieldSettings):
    type: Literal["select-box"]
    params: SelectBoxParams

    def detailed_check_value(
            self, field_name: str, value: str, objects: Optional[ObjectCollection], form_data: dict, soft_mode: bool
    ) -> Any:
        if self.params and self.params.strOptions:
            if value not in self.params.strOptions:
                if not soft_mode:
                    self.raise_error(field_name)
                else:
                    return None

            return value

        elif self.params and self.params.objOptions:
            if not objects:
                raise APIError(APIError.INTERNAL, "Object collection is not set")

            object_set = objects.get(self.params.objOptions.objectSetName, None)
            if not object_set:
                logger.error(
                    f"Malformed settings for select-box field {field_name}. "
                    f"Object set '{self.params.objOptions.objectSetName}' not found."
                )
                raise APIError(APIError.INTERNAL)

            filter_condition = self.params.objOptions.filterCondition
            if not filter_condition:
                for obj_instance in object_set:
                    if value == obj_instance.get(field_name, None):
                        return value

                if not soft_mode:
                    self.raise_error(field_name)
                else:
                    return None

            filter_condition_value = form_data.get(filter_condition, None)
            if not filter_condition_value:
                logger.error(
                    f"Malformed settings for select-box field {field_name}. "
                    f"Filter condition field {filter_condition} value not set."
                )
                raise APIError(APIError.INTERNAL)

            for obj_instance in object_set:
                if (value == obj_instance.get(field_name, None)
                        and obj_instance.get(filter_condition, None) == filter_condition_value):
                    return value

            if not soft_mode:
                self.raise_error(field_name)
            else:
                return None

        logger.error(f"Malformed settings for select-box field {field_name}")
        raise APIError(APIError.INTERNAL)


PHONE_RE = re.compile("^\\+[0-9+$]")


class PhoneFieldSettings(BaseFieldSettings):
    type: Literal["phone"]
    params: PhoneInputParams

    def detailed_check_value(
            self, field_name: str, value: str, objects: Optional[ObjectCollection], form_data: dict, soft_mode: bool
    ) -> Any:
        if not PHONE_RE.match(value):
            if not soft_mode:
                self.raise_error(field_name)
            else:
                return None

        return value


class DateFieldSettings(BaseFieldSettings):
    type: Literal["date"]

    def detailed_check_value(
            self, field_name: str, value: Any, objects: Optional[ObjectCollection], form_data: dict, soft_mode: bool
    ) -> Any:
        try:
            DateValue.model_validate(value)
            return value
        except pydantic.ValidationError as _:
            if not soft_mode:
                self.raise_error(field_name)
            else:
                return None


class CountryFieldSettings(BaseFieldSettings):
    type: Literal["country"]

    def detailed_check_value(
            self, field_name: str, value: str, objects: Optional[ObjectCollection], form_data: dict, soft_mode: bool
    ) -> Any:
        if value not in country_codes:
            if not soft_mode:
                self.raise_error(field_name)
            else:
                return None
        return value


class StringArrayFieldSettings(BaseFieldSettings):
    type: Literal["string-array"]
    params: TextInputParams | None = Field(default=None)

    def detailed_check_value(
            self, field_name: str, value: list[str], objects: Optional[ObjectCollection], form_data: dict, soft_mode: bool
    ) -> Any:
        if self.params and self.params.regexp:
            regexp = re.compile(self.params.regexp)
            for entry in value:
                if not regexp.match(entry):
                    if not soft_mode:
                        self.raise_error(field_name)
                    else:
                        return None

        return value


class ObjectParams(BaseModel):
    children: Dict[
        str,
        Annotated[
            Union[
                TextInputSettings,
                SelectBoxSettings,
                PhoneFieldSettings,
                DateFieldSettings,
                CountryFieldSettings,
                StringArrayFieldSettings,
                'ObjectFieldSettings',
            ],
            Field(..., discriminator='type')
        ]
    ]


class ObjectFieldSettings(BaseFieldSettings):
    type: Literal["object"]
    params: ObjectParams

    def detailed_check_value(
            self, field_name: str, value: list[str], objects: Optional[ObjectCollection], form_data: dict, soft_mode: bool
    ) -> Any:
        result = {}
        for sub_field_name, sub_field_settings in self.params.children.items():
            new_value = sub_field_settings.check_value(
                form_data=form_data.get(field_name, None),
                field_name=sub_field_name,
                objects=objects,
                soft_mode=soft_mode
            )
            if new_value:
                result[sub_field_name] = new_value

        return result


class AdvancedForm(BaseModel):
    fields: Dict[
        str,
        Annotated[
            Union[
                TextInputSettings,
                SelectBoxSettings,
                PhoneFieldSettings,
                DateFieldSettings,
                CountryFieldSettings,
                StringArrayFieldSettings,
                ObjectFieldSettings,
            ],
            Field(..., discriminator='type')
        ]
    ]
    objects: Optional[ObjectCollection] = Field(default=None)

    def check(self, form_data: Dict[str, Any], soft_mode: bool = False) -> Dict[str, Any]:
        """
        :param form_data: data in a form of dictionary
        :param soft_mode: Soft mode allows to left required fields unfilled
        :return: None
        """
        if not isinstance(form_data, Dict):
            raise APIError(
                APIError.FORM_DATA,
                f"Form data is incorrect (expected JSON encoded object)"
            )

        result: Dict[str, Any] = {}
        for field_name, field_settings in self.fields.items():
            new_value = field_settings.check_value(form_data, field_name, self.objects, soft_mode)
            if new_value:
                result[field_name] = new_value

        return result
