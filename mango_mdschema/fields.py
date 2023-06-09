import logging
import re
from datetime import datetime, date, time

from irods.meta import iRODSMeta
import validators

from mango_mdschema.helpers import check_metadata, bold


class Field:
    def __init__(self, name: str, content: dict):
        """Class representing a field of a metadata schema.

        Args:
            name (str): Name of the field, without flattening.
            content (dict): The contents of the JSON object the field comes from.

        Attributes:
            name (str): The name of the field.
            type (str): The type of the field, defined within the subclass.
            required (bool): Whether the field is required.
            default (any, optional): The default value for the field, if it is required.
            repeatable (bool): Whether the field is repeatable.
            flattened_name (str): The flattened name of the field, for the AVU.
            description (str): Description of the criteria for the field.

        Raises:
            KeyError: When the contents don't include a type.
        """
        self.name = name

        if not "type" in content:
            raise KeyError("A field must have a type.")

        self.required = "required" in content and content["required"]
        self.default = content["default"] if "default" in content else None
        self.repeatable = "repeatable" in content and content["repeatable"]

    def start_description(self):
        if not self.required:
            def_message = ""
        elif self.type == "object":
            n_required = len(self.required_fields)
            def_message = f" ({n_required} of its {len(self.fields)} fields {'is' if n_required == 1 else 'are'} required.)"
        else:
            def_message = f" {bold('Default')}: {self.default}."
        self.description = "\n".join(
            [
                f"{bold('Type')}: {self.type}.",
                f"{bold('Required')}: {self.required}.{def_message}",
                f"{bold('Repeatable')}: {self.repeatable}.",
            ]
        )

    def flatten_name(self, prefix: str):
        """Flatten the name for the AVU.

        Args:
            prefix (str): Prefix to add to the name of the field.
        """
        self.flattened_name = f"{prefix}.{self.name}"

    def create_avu(self, value, index, verbose):
        raise NotImplementedError

    def __str__(self):
        return self.description

    @staticmethod
    def choose_class(name: str, content: dict):
        """Identify the type of field.

        Args:
            name (str): Name of the field, to initiate it.
            content (dict): Contents of the JSON the field comes from.

        Raises:
            KeyError: When the JSON does not include a 'type' key.
            ValueError: When the value of the 'type' is not supported.

        Returns:
            Field: A representation of the field itself.
        """
        if not "type" in content:
            raise KeyError("A field should have a type.")
        elif content["type"] == "object":
            return CompositeField(name, content)
        elif content["type"] == "select":
            return MultipleField(name, content)
        elif content["type"] in SimpleField.text_options:
            return SimpleField(name, content)
        else:
            raise ValueError(f"The type of the '{name}' field is not valid.")


class SimpleField(Field):
    text_options = [
        "text",
        "textarea",
        "email",
        "url",
        "date",
        "time",
        "datetime-local",
        "integer",
        "float",
        "checkbox",
    ]

    types = {
        "integer": int,
        "float": float,
        "date": date,
        "time": time,
        "datetime-local": datetime,
    }

    types_with_regex = ["text", "email", "url"]

    def __init__(self, name: str, content: dict):
        """Class representing a simple field.

        Args:
            name (str): Name of the field.
            content (dict): Contents of the JSON that the field comes from.

        Attributes:
            minimum (int or float, default): If `self.type` is 'integer' or 'float',
                the minimum possible value.
            maximum (int or float, default): If `self.type` is 'integer' or 'float',
                the maximum possible value.
            pattern (str): If `self.type` is 'text', 'email' or 'url',
                the pattern for regex check.

        Raises:
            ValueError: When the type of the field is not valid.
        """
        super().__init__(name, content)

        if content["type"] not in SimpleField.text_options:
            raise ValueError("The type of the field is not valid.")
        else:
            self.type = content["type"]

        extra = ""

        if self.type in ["integer", "float"]:
            self.converter = SimpleField.types[self.type]
            self.minimum = (
                self.converter(content["minimum"]) if "minimum" in content else None
            )
            self.maximum = (
                self.converter(content["maximum"]) if "maximum" in content else None
            )

            if self.minimum is not None and self.maximum is not None:
                extra = f"{self.type} between {self.minimum} and {self.maximum}."
            elif self.minimum is not None:
                extra = f"{self.type} larger than {self.minimum}."
            elif self.maximum is not None:
                extra = f"{self.type} smaller than {self.maximum}."
        elif self.type in SimpleField.types_with_regex:
            self.pattern = content["pattern"] if "pattern" in content else None
            if self.pattern is not None:
                extra = f"matching the following regex: \033[91m{self.pattern}\033[0m."

        self.start_description()
        self.description = (
            "\n".join([self.description, extra]) if extra else self.description
        )

    def _validate_number(self, value) -> str:
        """Validate the value of an integer or float.

        Args:
            value (int | float | str): Value provided for a field that is an integer or a float.

        Returns:
            str: The final value if validated, else False.
        """
        try:
            value = self.converter(value)
        except ValueError:
            return False
        return (
            str(value)
            if validators.between(value, min=self.minimum, max=self.maximum)
            else False
        )

    def _validate_datetime(self, value) -> str:
        """Validate the value of a date, time or datetime field.

        A date can be provided as `datetime.date` or something that can be converted to it via
        `datetime.date.fromisoformat()` or `datetime.date.fromtimestamp()`.
        A datetime can be provided as `datetime.datetime` or something that can be converted to it via
        `datetime.datetime.fromisoformat()` or `datetime.datetime.fromtimestamp()`.
        A date can be provided as `datetime.time` or something that can be converted to it via
        `datetime.time.fromisoformat()`.

        Args:
            value (date | time | datetime | str): The value of an AVU that should be date, time, or datetime.

        Returns:
            str: The date, time or datetime in ISO format, or False if the input format is not valid.
        """
        this_type = SimpleField.types[self.type]
        tries = 2
        if type(value) == str:
            if tries == 2:
                try:
                    value = this_type.fromisoformat(value)
                except:
                    tries -= 1
            if tries == 1 and self.type != "time":
                try:
                    value = this_type.fromtimestamp(value)
                except:
                    pass
        return this_type.isoformat(value) if type(value) == this_type else False

    def validate(self, value: any) -> str:
        """Validate a value provided for the AVU.

        Args:
            value (any): A single value provided for an AVU based on a simple field.

        Returns:
            str: The final, converted value, or `False` if it is not valid.
        """
        if self.type in ["integer", "float"]:
            # validate as number if it's a number
            return self._validate_number(value)
        elif self.type in SimpleField.types_with_regex:
            # check regex if appropriate
            if self.pattern is not None and not re.search(self.pattern, value):
                return False
            # validate email (if regex passed)
            if self.type == "email":
                return value if validators.email(value) else False
            # validate url (if regex passed)
            elif self.type == "url":
                return value if validators.url(value) else False
        # validate dates, times and datetimes
        elif self.type in ["date", "time", "datetime-local"]:
            return self._validate_datetime(value)
        # validate checkboxes
        elif self.type == "checkbox":
            return "true" if type(value) == bool else False

        # if nothing went wrong, just return the value (text that matched regex, textbox)
        return str(value)

    def create_avu(self, value: any, unit: str = None, verbose: bool = False):
        if type(value) == list:
            if not self.repeatable:
                raise TypeError(
                    f"`{self.flattened_name}` is not repeatable, a single value should be provided instead."
                )
            else:
                valid_values = [x for x in value if self.validate(x)]
                if len(valid_values) == 0:
                    return self.deal_with_invalid(value, unit)
                elif len(valid_values) < len(value):
                    invalid_values = ", ".join(
                        [x for x in value if not x in valid_values]
                    )
                    logging.warning(
                        f"The following values provided for `{self.flattened_name}` are not valid and will be ignored: {invalid_values}."
                    )
                return [iRODSMeta(self.flattened_name, x, unit) for x in valid_values]
        else:
            validated_value = self.validate(value)
            return (
                [iRODSMeta(self.flattened_name, validated_value, unit)]
                if validated_value
                else self.deal_with_invalid(value, unit)
            )

    def deal_with_invalid(self, value, unit):
        if not self.required:
            logging.warning(
                f"The values provided for `{self.flattened_name}` are not valid and will be ignored."
            )
            return [None]
        elif self.default:
            logging.warning(
                f"The values provided for `{self.flattened_name}` are not valid: the default will be used."
            )
            return [iRODSMeta(self.flattened_name, self.default, unit)]
        raise ValueError(
            f"None of the values provided for `{self.flattened_name}` are valid."
        )


class CompositeField(Field):
    def __init__(self, name: str, content: dict):
        """Class representing a composite field.

        Args:
            name (str): Name of the field.
            content (dict): Contents of the JSON the field comes from.

        Attributes:
            fields (dict of Field): Collection of subfields.

        Raises:
            ValueError: When the 'type' attribute of `content` is not 'object'.
            KeyError: When the 'properties' attribute is missing from `content`.
            TypeError: When the 'properties' attribute of `content` is not a dictionary.
        """
        super().__init__(name, content)

        if content["type"] != "object":
            raise ValueError("The type of the field must be 'object'.")
        else:
            self.type = content["type"]

        if not "properties" in content:
            raise KeyError("A composite field requires a 'properties' attribute.")
        elif type(content["properties"]) != dict:
            raise TypeError(
                "The 'properties' attribute of a composite field must be a dictionary."
            )
        else:
            self.fields = {
                k: Field.choose_class(k, v) for k, v in content["properties"].items()
            }
            self.required_fields = {
                subfield.name: subfield.default
                for subfield in self.fields.values()
                if subfield.required
            }
            if len(self.required_fields) > 0:
                self.required = True

        self.start_description()
        extra = f"\n\nComposed of the following fields:\n"
        field_description = "\n\n".join(
            f"\033[4m{subfield.name}\033[0m\n{subfield.description}"
            for subfield in self.fields.values()
        )
        self.description = self.description + extra + field_description

    def flatten_name(self, prefix: str):
        """Flatten the name for the AVUs of the subfields.

        Args:
            prefix (str): Prefix to add to the name of the field.
        """
        super().flatten_name(prefix)
        for subfield in self.fields.values():
            subfield.flatten_name(self.flattened_name)

    def create_avu(self, value: dict, unit: str = None, verbose: bool = False) -> list:
        """Generate an iRODS AVU based on one or more values.

        Args:
            value (dict | list of dict): The dictionary with subfields for the composite field.
            unit (str, default): The unit for the AVU. By default it is None.
                It is a stringified integer when the field belongs to a composite field.
            verbose (bool, optional): Whether warnings should be raised when fields are ignored.
                See `schema.check_metadata()`.

        Raises:
            TypeError: When a list if provided while the field is not repeatable or a dictionary is not provided.

        Returns:
            list of iRODSMeta: List of AVUs.
        """
        if type(value) == list:
            if not self.repeatable:
                raise TypeError(
                    f"`{self.flattened_name}` is not repeatable, a dictionary should be provided instead."
                )
            else:
                avus = [
                    check_metadata(
                        self, x, verbose, CompositeField.get_unit(i + 1, unit)
                    )
                    for i, x in enumerate(value)
                ]
                return [avu for avu_list in avus for avu in avu_list]
        elif type(value) != dict:
            raise TypeError(
                f"The value of `{self.flattened_name}` should be a dictionary."
            )
        else:
            return check_metadata(
                self, value, verbose, CompositeField.get_unit(1, unit)
            )

    @staticmethod
    def get_unit(this_unit: int, parent_unit: str = None):
        return str(this_unit) if parent_unit is None else f"{parent_unit}.{this_unit}"


class MultipleField(Field):
    def __init__(self, name: str, content: dict):
        """A class representing a multiple-choice field.

        Args:
            name (str): Name of the field.
            content (dict): Contents of the JSON the field comes from.

        Attributes:
            multiple (bool): Whether more than one value can be given.
            values (list): The possible values.

        Raises:
            KeyError: When the 'multiple' or 'values' attributes are missing from `content`.
            ValueError: When the 'multiple' attribute of `content` is not boolean
                or the 'values' attribute is not a list.
        """
        super().__init__(name, content)
        if content["type"] != "select":
            raise ValueError("The type of the field must be 'select'.")
        else:
            self.type = content["type"]

        if not "multiple" in content:
            raise KeyError(
                "A multiple-choice field requires a 'multiple' boolean attribute."
            )
        elif type(content["multiple"]) != bool:
            raise ValueError("The 'multiple' attribute must be boolean.")
        else:
            self.multiple = content["multiple"]

        if not "values" in content:
            raise KeyError("A multiple-choice field requires a 'values' attribute.")
        elif type(content["values"]) != list:
            raise ValueError("The 'values' attribute must be a list.")
        else:
            self.values = content["values"]

        self.start_description()
        multi_description = f'\nChoose {"at least" if self.multiple else "only"} one of the following values:\n'
        values_description = "- " + "\n- ".join(self.values)
        self.description = self.description + multi_description + values_description

    def create_avu(self, value: any, unit: str = None, verbose: bool = False) -> list:
        """Generate an iRODS AVU based on one or more values.

        Args:
            value (any): A list of values or one value of the metadata.
            unit (str, optional): The unit for the AVU. By default it is None.
                It is a stringified integer when the field belongs to a composite field.
            verbose (bool, optional): Not implemented

        Raises:
            ValueError: When a single-value multiple-choice field is given multiple values
                or none of the provided values are valid.

        Returns:
            list of iRODSMeta or None: The AVUS with the valid values, or None if
                the values are invalid but the field is not required.
        """
        if type(value) == list:  # if we have multiple values
            if not self.multiple:
                raise ValueError(
                    "A single-value multiple-choice field can only receive one value."
                )
            else:  # if it's a multiple-value multiple-choice in its own right
                not_acceptable = [x for x in value if not x in self.values]
                if len(not_acceptable) == len(value):
                    message = f"None of the values provided for `{self.flattened_name}` are valid."
                    if self.required:
                        raise ValueError(message)
                    else:
                        logging.warning(message)
                        return None
                elif len(not_acceptable) > 0:
                    not_acceptable_values = ", ".join(not_acceptable)
                    logging.warning(
                        f"The following values provided for `{self.flattened_name}` are not acceptable and will be ignored: {not_acceptable_values}"
                    )
                return [
                    iRODSMeta(self.flattened_name, x, unit)
                    for x in value
                    if x in self.values
                ]

        else:  # if we have only one value
            if value in self.values:
                return [
                    iRODSMeta(self.flattened_name, value, unit)
                ]  # the value is correct!
            elif not self.required:
                # the value is not correct but the field is not required anyways
                logging.warning(
                    f"The value provided for `{self.flattened_name}` is not valid and will be ignored."
                )
                return None
            elif self.default is not None:
                # the value is not correct but the field is required and there is a default
                logging.warning(
                    f"The value provided for `{self.flattened_name}` is not valid, the default value will be used instead."
                )
                return [iRODSMeta(self.flattened_name, self.default, unit)]
            else:
                # the value is not correct but the field is required and there is no default
                raise ValueError(
                    f"The value provided for `{self.flattened_name}` is not valid but the field is required and there is no default."
                )
