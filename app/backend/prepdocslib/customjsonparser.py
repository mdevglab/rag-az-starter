import json
import logging
from typing import IO, AsyncGenerator, Dict, Any, Optional
import asyncio
from datetime import datetime, timezone

from .page import Page
from .parser import Parser

try:
    from dateutil import parser as dateutil_parser
    from dateutil.parser import ParserError
except ImportError:
    logging.error("python-dateutil library not found. Please install it: pip install python-dateutil")
    dateutil_parser = None
    ParserError = Exception

logger = logging.getLogger(__name__)

class SpecificJsonParser(Parser):
    """
    Parses JSON files expecting a specific structure.
    Converts the 'updatedate' field to ISO 8601 UTC format for Edm.DateTimeOffset.
    {
      "value": [
        {
          "content": "Text content to be indexed...",
          "url": "URL or path to the original file...",
          "updatedate": "Date string in various formats..."
        }
      ]
    }
    - 'content' becomes the text of a single Page object.
    - 'url' is stored in Page metadata mapped to `metadata_field_name`.
    - 'updatedate' is parsed, converted to UTC ISO 8601 format, and stored in Page metadata mapped to `updatedate_metadata_field`.
    Yields a single Page object per item in the 'value' list.
    """

    def __init__(self, metadata_field_name: str = "sourcefile", updatedate_metadata_field: str = "updatedate"):
        self.metadata_field_name = metadata_field_name
        self.updatedate_metadata_field = updatedate_metadata_field
        logger.info("SpecificJsonParser initialized to map JSON 'url' to '%s' and 'updatedate' to '%s' (converting to ISO 8601 UTC)",
                     self.metadata_field_name, self.updatedate_metadata_field)
        if dateutil_parser is None:
             logger.error("Date parsing disabled because 'python-dateutil' is not installed.")

    async def parse(self, content: IO[bytes], file_path: Optional[str] = None) -> AsyncGenerator[Page, None]:
        """
        Parses the JSON content asynchronously, handling date conversion.

        Args:
            content (IO[bytes]): A file-like object containing the JSON byte content.
            file_path (Optional[str]): The path/name of the file being parsed (for logging).

        Yields:
            Page: A Page object containing the extracted text and metadata for each valid item.

        Raises:
            ValueError: If the JSON is invalid or top-level structure is wrong.
        """
        filename_for_log = file_path or "unknown file"
        logger.debug("Parsing specific JSON structure from: %s", filename_for_log)
        try:
            loop = asyncio.get_running_loop()
            try:
                json_content_bytes = content.read()
                data = await loop.run_in_executor(None, json.loads, json_content_bytes)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON structure in file {filename_for_log}: {e}") from e
            except Exception as e:
                raise ValueError(f"Could not read or decode JSON file {filename_for_log}: {e}") from e

            # --- Basic Structure Checks ---
            if not isinstance(data, dict):
                logger.error("JSON file '%s' did not parse into a dictionary. Skipping.", filename_for_log)
                return
            value_list = data.get("value")
            if not isinstance(value_list, list):
                logger.error("Key 'value' in JSON file '%s' is missing or not a list. Skipping.", filename_for_log)
                return
            if not value_list:
                logger.warning("The list associated with key 'value' in JSON file '%s' is empty. Skipping.", filename_for_log)
                return

            # --- Iterate through items in the 'value' list ---
            for index, item_data in enumerate(value_list):
                item_log_prefix = f"Item {index} in {filename_for_log}" # For clearer logging

                if not isinstance(item_data, dict):
                    logger.error("%s is not a dictionary (object). Skipping item.", item_log_prefix)
                    continue # Skip this item, process next

                logger.debug("Processing %s. Keys found: %s", item_log_prefix, list(item_data.keys()))
                text_content = item_data.get("content")
                file_url = item_data.get("url")
                update_date_val = item_data.get("updatedate") # Original date string

                if not isinstance(text_content, str) or not text_content.strip():
                    logger.error("'content' field is missing, empty, or not a string in %s. Skipping item.", item_log_prefix)
                    continue # Skip this item

                page_metadata: Dict[str, Any] = {}

                # Process 'url'
                if isinstance(file_url, str) and file_url.strip():
                    page_metadata[self.metadata_field_name] = file_url
                    logger.debug("Extracted '%s': %s from %s", self.metadata_field_name, file_url, item_log_prefix)
                else:
                    logger.warning("'url' field is missing/empty/not string in %s. Metadata '%s' will not be set.",
                                   item_log_prefix, self.metadata_field_name)

                # --- Process 'updatedate' with CONVERSION ---
                if dateutil_parser and isinstance(update_date_val, str) and update_date_val.strip():
                    try:
                        # 1. Parse the date string using dateutil (handles many formats)
                        dt_obj = dateutil_parser.parse(update_date_val)

                        # 2. Ensure the datetime object is timezone-aware and in UTC
                        if dt_obj.tzinfo is None or dt_obj.tzinfo.utcoffset(dt_obj) is None:
                            # Input was naive (no timezone). Assume it's UTC.
                            # If you know source is local time, you'd need to localize then convert.
                            dt_utc = dt_obj.replace(tzinfo=timezone.utc)
                            logger.debug("Parsed naive date '%s' as UTC for %s", update_date_val, item_log_prefix)
                        else:
                            # Input had timezone info. Convert it to UTC.
                            dt_utc = dt_obj.astimezone(timezone.utc)
                            logger.debug("Parsed timezone-aware date '%s' and converted to UTC for %s", update_date_val, item_log_prefix)

                        # 3. Format to ISO 8601 with 'Z' specifier (required by Azure Search)
                        # Use strftime for precise format control including 'Z'
                        iso_date_string = dt_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
                        # If you need millisecond precision:
                        # iso_date_string = dt_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

                        page_metadata[self.updatedate_metadata_field] = iso_date_string
                        logger.debug("Stored '%s': %s (converted from '%s') for %s",
                                     self.updatedate_metadata_field, iso_date_string, update_date_val, item_log_prefix)

                    except (ParserError, ValueError, OverflowError) as e:
                        # Log error if parsing fails
                        logger.warning("Could not parse 'updatedate' string '%s' into a valid datetime object in %s: %s. Metadata '%s' will not be set.",
                                       update_date_val, item_log_prefix, e, self.updatedate_metadata_field)
                    except Exception as e:
                        # Catch unexpected errors during date processing
                         logger.exception("Unexpected error processing 'updatedate' string '%s' in %s. Metadata '%s' will not be set.",
                                       update_date_val, item_log_prefix, self.updatedate_metadata_field)

                elif not dateutil_parser:
                     logger.warning("'python-dateutil' not installed, cannot parse 'updatedate' field '%s' in %s. Metadata '%s' will not be set.",
                                     update_date_val, item_log_prefix, self.updatedate_metadata_field)
                else:
                    # Handle cases where 'updatedate' is missing, empty, or not a string
                    logger.warning("'updatedate' field is missing, empty, or not a string ('%s') in %s. Metadata '%s' will not be set.",
                                   update_date_val, item_log_prefix, self.updatedate_metadata_field)

                # Create Page object for this item
                page = Page(
                    page_num=index, # Use index as page number
                    offset=0,
                    text=text_content,
                    metadata=page_metadata
                )
                logger.debug("Yielding Page %d for %s", index, item_log_prefix)
                yield page

        except ValueError as e:
             # Catches JSON structure errors raised earlier
             logger.error("Value error while parsing JSON %s: %s", filename_for_log, e)
             raise # Re-raise specific value errors
        except Exception as e:
            logger.exception("Unexpected error parsing specific JSON file %s", filename_for_log)
            # Decide if you want to raise, log, or yield an empty page/skip