import json
import logging
from typing import IO, AsyncGenerator, Dict, Any, Optional
import asyncio

# Import the MODIFIED Page class
from .page import Page
from .parser import Parser

logger = logging.getLogger(__name__)

class SpecificJsonParser(Parser):
    """
    Parses JSON files expecting a specific structure:
    {
        "content": "Text content to be indexed...",
        "url": "URL or path to the original file..."
        "updatedate": "Date string..."
    }
    - 'content' becomes the text of a single Page object.
    - 'url' is stored in Page metadata mapped to `metadata_field_name` (e.g., 'sourcefile').
    - 'updatedate' is stored in Page metadata mapped to 'updatedate'.
    Yields a single Page object.
    """

    def __init__(self, metadata_field_name: str = "sourcefile", updatedate_metadata_field: str = "updatedate"):
        self.metadata_field_name = metadata_field_name
        self.updatedate_metadata_field = updatedate_metadata_field
        logger.info("SpecificJsonParser initialized to map JSON 'url' to '%s' and 'updatedate' to '%s'", self.metadata_field_name, self.updatedate_metadata_field)

    async def parse(self, content: IO[bytes], file_path: Optional[str] = None) -> AsyncGenerator[Page, None]:
        """
        Parses the JSON content asynchronously.

        Args:
            content (IO[bytes]): A file-like object containing the JSON byte content.
            file_path (Optional[str]): The path/name of the file being parsed (for logging).

        Yields:
            Page: A Page object containing the extracted text and metadata.

        Raises:
            ValueError: If the JSON is invalid, 'content' is missing/not a string,
                        or other parsing errors occur.
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

            # --- Check 1: Top level must be a dictionary ---
            if not isinstance(data, dict):
                logger.error("JSON file '%s' did not parse into a dictionary (object). Parsed type: %s. Skipping.",
                             filename_for_log, type(data).__name__)
                return

            # --- Check 2: Top level dictionary must have 'value' key ---
            value_list = data.get("value")
            if value_list is None:
                 logger.error("Required key 'value' not found in top-level JSON object in file '%s'. Skipping.", filename_for_log)
                 return

            # --- Check 3: 'value' must be a list ---
            if not isinstance(value_list, list):
                 logger.error("Key 'value' in JSON file '%s' does not contain a list. Found type: %s. Skipping.",
                              filename_for_log, type(value_list).__name__)
                 return

            # --- Check 4: The list under 'value' must not be empty ---
            if not value_list: # Checks if the list is empty
                 logger.warning("The list associated with key 'value' in JSON file '%s' is empty. Skipping.", filename_for_log)
                 return

            # --- Access the first (and only expected) item in the list ---
            item_data = value_list[0]

            # --- Check 5: The item in the list must be a dictionary ---
            if not isinstance(item_data, dict):
                logger.error("The first item in the 'value' list in file '%s' is not a dictionary (object). Found type: %s. Skipping.",
                             filename_for_log, type(item_data).__name__)
                return
            
            logger.debug("Keys found in item_data for file '%s': %s", filename_for_log, list(item_data.keys()))
            text_content = item_data.get("content")
            file_url = item_data.get("url")
            update_date_val = item_data.get("updatedate")

            if not isinstance(text_content, str) or not text_content.strip():
                logger.error("'content' field is missing, empty, or not a string in JSON file: %s. Skipping.", filename_for_log)
                return # Stop yielding if content is invalid

            page_metadata: Dict[str, Any] = {}
            if isinstance(file_url, str) and file_url.strip():
                page_metadata[self.metadata_field_name] = file_url
                logger.debug("Extracted '%s': %s from %s", self.metadata_field_name, file_url, filename_for_log)
            else:
                logger.warning("'url' field is missing, empty, or not a string in JSON file: %s. Metadata '%s' will not be set.",
                               filename_for_log, self.metadata_field_name)
            
            # --- ADD 'updatedate' METADATA ---
            # Store as string for simplicity, assuming Edm.String in index.
            # Add validation/conversion here if target type is Edm.DateTimeOffset  ## TODO
            if isinstance(update_date_val, str) and update_date_val.strip():
                page_metadata[self.updatedate_metadata_field] = update_date_val
                logger.debug("Extracted '%s': %s from JSON 'updatedate' field in %s",
                             self.updatedate_metadata_field, update_date_val, filename_for_log)
            else:
                 logger.warning("'updatedate' field is missing, empty, or not a string in JSON file: %s. Metadata '%s' will not be set.",
                                filename_for_log, self.updatedate_metadata_field)
                 
            # Create *one* Page object (page_num=0, offset=0)
            page = Page(
                page_num=0,
                offset=0,
                text=text_content,
                metadata=page_metadata  # Pass the extracted metadata
            )
            logger.debug("Yielding Page for %s with text length %d and metadata %s",
                         filename_for_log, len(page.text), page.metadata)
            yield page

        except ValueError as e:
             logger.error("Value error while parsing JSON %s: %s", filename_for_log, e)
             raise # Re-raise specific value errors
        except Exception as e:
            logger.exception("Unexpected error parsing specific JSON file %s", filename_for_log)
            # Decide if you want to raise, log, or yield an empty page/skip