# prepdocslib/filestrategy.py
import logging
from typing import List, Optional, Dict, Any # Added Dict, Any

from azure.core.credentials import AzureKeyCredential

# Assuming these imports are correct relative to your project structure
from .blobmanager import BlobManager
from .embeddings import ImageEmbeddings, OpenAIEmbeddings
from .fileprocessor import FileProcessor
# Assuming File provides filename(), content(), url(), file_extension(), close(), acls
from .listfilestrategy import File, ListFileStrategy
from .mediadescriber import ContentUnderstandingDescriber
# Import the MODIFIED Section class from searchmanager
from .searchmanager import SearchManager, Section
from .strategy import DocumentAction, SearchInfo, Strategy
# Import Page to access its metadata attribute
from .page import Page
# Import SplitPage for type hinting
from .textsplitter import SplitPage

logger = logging.getLogger("scripts") # Use the logger name from your main script


async def parse_file(
    file: File,
    file_processors: dict[str, FileProcessor],
    category: Optional[str] = None,
    image_embeddings: Optional[ImageEmbeddings] = None, # Keep param, even if unused in this specific func
) -> List[Section]:
    """
    Parses a File object using the appropriate parser and splitter,
    propagating metadata from Page objects to Section objects.

    Args:
        file (File): The file object to process.
        file_processors (dict): Dictionary mapping file extensions to FileProcessors.
        category (Optional[str]): Optional category to assign to sections.
        image_embeddings (Optional[ImageEmbeddings]): Passed through but not used here.

    Returns:
        List[Section]: A list of Section objects ready for indexing, including metadata.
    """
    key = file.file_extension().lower()
    processor = file_processors.get(key)
    filename = file.filename() # Get filename for logging

    if processor is None:
        logger.info("Skipping '%s', no parser found for extension '%s'.", filename, key)
        return []

    logger.info("Ingesting '%s' using parser %s and splitter %s",
                filename, type(processor.parser).__name__, type(processor.splitter).__name__)

    pages: List[Page] = []
    try:
        # Pass filename to parser if it accepts it (our SpecificJsonParser does via file_path)
        # Check if parse method accepts file_path kwarg, adapt if necessary
        # For simplicity assuming it does or ignores unknown kwargs
        pages = [page async for page in processor.parser.parse(content=file.content, file_path=filename)]
    except Exception as e:
        logger.error("Error during parsing of file '%s': %s", filename, e)
        # Optionally re-raise or return empty list depending on desired behavior
        return [] # Stop processing this file on parsing error

    logger.info("Parsed %d page(s) from '%s'", len(pages), filename)
    if not pages:
        return []

    # Build a lookup for metadata based on page number
    # Crucial for transferring metadata from the original Page to the Section
    metadata_lookup: Dict[int, Dict[str, Any]] = {p.page_num: p.metadata for p in pages if p.metadata}
    if metadata_lookup:
         #logger.debug("Metadata found on parsed pages for %s: %s", filename, metadata_lookup)
         logger.debug(f"Metadata found on parsed pages for {filename}")

    sections: List[Section] = []
    try:
        # Use the splitter to get SplitPage objects from the parsed Pages
        logger.info(f"Splitting '%s' into sections..., {filename} {type(processor.splitter).__name__}")

        # --- Consume the splitter output iteratively ---
        # This assumes split_pages yields SplitPage objects or returns an iterable of them.
        split_page_count = 0
        # Call the splitter - it might return a list OR a generator
        split_iterable = processor.splitter.split_pages(pages)

        # Iterate through the results regardless of whether it's a list or generator
        for split_page in split_iterable:
            split_page_count += 1
            section = Section(split_page, content=file, category=category)
            original_page_metadata = metadata_lookup.get(split_page.page_num)
            section.metadata = original_page_metadata.copy() if original_page_metadata else {}
            sections.append(section)
        # --- End iterative consumption ---

        logger.info("Finished splitting '%s', generated %d sections", filename, split_page_count)
        if not sections and pages:
             logger.warning(...) # Keep warning

    except TypeError as te:
        # Catch the specific TypeError if it happens here
        #logger.error("TypeError during splitting of file '%s': %s. This might indicate an issue with the splitter's internal logic.", filename, te)
        logger.error(
            f"TypeError during splitting of file '{filename}': {te!s}. "
            f"Type of splitter: {type(processor.splitter).__name__}. "
            f"Type of pages input: {type(pages).__name__}. Pages count: {len(pages) if isinstance(pages, list) else 'N/A'}.",
            exc_info=True # Include full traceback in the log
        )
        return []
    except Exception as e:
        logger.error("Unexpected error during splitting of file '%s': %s", filename, e)
        return []

        # Assuming split_pages takes list of Page objects
        split_pages_results: List[SplitPage] = processor.splitter.split_pages(pages)
        split_page_count = len(split_pages_results)
        logger.info("Split '%s' into %d potential sections", filename, split_page_count)

        for split_page in split_pages_results:
            # Create the Section object using the constructor defined in searchmanager.py
            # It takes SplitPage and the original File object
            section = Section(split_page, content=file, category=category)

            # Retrieve metadata using the lookup based on the original page number
            # and assign it to the section's metadata attribute.
            original_page_metadata = metadata_lookup.get(split_page.page_num)
            if original_page_metadata:
                section.metadata = original_page_metadata.copy() # Assign a copy
                logger.debug("Assigned metadata %s to section from page %d of '%s'",
                             original_page_metadata, split_page.page_num, filename)
            else:
                # Ensure metadata is always at least an empty dict
                section.metadata = {}

            sections.append(section)

        if not sections and pages:
             logger.warning("File '%s' was parsed into %d pages, but splitting resulted in 0 sections.", filename, len(pages))

    except Exception as e:
        logger.error("Error during splitting of file '%s': %s", filename, e)
        # Optionally re-raise or return empty list
        return [] # Stop processing this file on splitting error

    # Warning about image embeddings granularity (keep as is)
    if image_embeddings and len(pages) > 1:
         logger.warning("Each page was split into smaller chunks of text, but image embeddings (if used) might relate to the entire page.")

    logger.info("Successfully prepared %d sections for file '%s'", len(sections), filename)
    return sections


class FileStrategy(Strategy):
    """
    Strategy for ingesting documents using file processors, handling metadata propagation.
    """

    def __init__(
        self,
        list_file_strategy: ListFileStrategy,
        blob_manager: BlobManager, # Keep if blob uploads are needed
        search_info: SearchInfo,
        file_processors: dict[str, FileProcessor], # This will include our custom JSON parser
        document_action: DocumentAction = DocumentAction.Add,
        embeddings: Optional[OpenAIEmbeddings] = None,
        image_embeddings: Optional[ImageEmbeddings] = None,
        search_analyzer_name: Optional[str] = None,
        use_acls: bool = False,
        category: Optional[str] = None,
        use_content_understanding: bool = False, # Keep CU params if needed
        content_understanding_endpoint: Optional[str] = None,
    ):
        self.list_file_strategy = list_file_strategy
        self.blob_manager = blob_manager
        self.file_processors = file_processors
        self.document_action = document_action
        self.embeddings = embeddings
        self.image_embeddings = image_embeddings
        self.search_analyzer_name = search_analyzer_name
        self.search_info = search_info
        self.use_acls = use_acls
        self.category = category
        self.use_content_understanding = use_content_understanding
        self.content_understanding_endpoint = content_understanding_endpoint
        # Instantiate SearchManager here or within run()
        # Passing necessary flags based on self attributes
        self.search_manager = SearchManager(
             search_info=self.search_info,
             search_analyzer_name=self.search_analyzer_name,
             use_acls=self.use_acls,
             # Assuming FileStrategy doesn't use integrated vectorization path
             use_int_vectorization=False,
             embeddings=self.embeddings,
             search_images=(self.image_embeddings is not None)
        )


    async def setup(self):
        """Sets up the necessary Azure resources, primarily the search index."""
        # SearchManager handles index creation logic internally now
        await self.search_manager.create_index()

        # Keep Content Understanding setup if used
        if self.use_content_understanding:
            if self.content_understanding_endpoint is None:
                raise ValueError("Content Understanding is enabled but no endpoint was provided")
            if isinstance(self.search_info.credential, AzureKeyCredential):
                raise ValueError("AzureKeyCredential is not supported for Content Understanding")
            # Assuming ContentUnderstandingDescriber exists and works as intended
            cu_manager = ContentUnderstandingDescriber(self.content_understanding_endpoint, self.search_info.credential)
            await cu_manager.create_analyzer()


    async def run(self):
        """Executes the strategy based on the document_action."""

        if self.document_action == DocumentAction.Add:
            logger.info("Starting 'Add' document action using FileStrategy.")
            files = self.list_file_strategy.list()
            file_count = 0
            processed_files = 0
            failed_files = 0
            async for file in files:
                file_count += 1
                sections = [] # Ensure sections is reset for each file
                filename = file.filename() # Get filename early for logging
                logger.info(f"Processing file {file_count}: {filename}")
                try:
                    # Call the modified parse_file, which handles metadata transfer
                    sections = await parse_file(file, self.file_processors, self.category, self.image_embeddings)

                    if sections:
                        logger.debug("Generated %d sections for file %s", len(sections), filename)
                        # --- CRITICAL: Generate Section IDs before uploading ---
                        for i, section in enumerate(sections):
                             try:
                                section.create_section_id(section_index=i)
                             except Exception as id_err:
                                 logger.error("Error generating ID for section %d of file %s: %s. Skipping section.", i, filename, id_err)
                                 # Remove section if ID generation failed? Or handle differently?
                                 # For now, let's assume it might proceed without ID, causing upload failure later.

                        # Upload blob (optional, based on strategy needs)
                        blob_sas_uris = None
                        if self.blob_manager: # Check if blob manager is configured/needed
                            try:
                                blob_sas_uris = await self.blob_manager.upload_blob(file)
                                logger.debug("Uploaded blob for %s", filename)
                            except Exception as blob_err:
                                logger.error("Failed to upload blob for %s: %s", filename, blob_err)
                                # Decide if this is a fatal error for the file or just a warning

                        # Get image embeddings (optional)
                        blob_image_embeddings: Optional[List[List[float]]] = None
                        if self.image_embeddings and blob_sas_uris:
                             try:
                                logger.debug("Generating image embeddings for %s", filename)
                                blob_image_embeddings = await self.image_embeddings.create_embeddings(blob_sas_uris)
                             except Exception as img_emb_err:
                                 logger.error("Failed to create image embeddings for %s: %s", filename, img_emb_err)

                        # Update search index - SearchManager now handles metadata via Section
                        # Pass the list of Section objects (which now contain metadata and IDs)
                        await self.search_manager.update_content(sections, blob_image_embeddings)
                        processed_files += 1
                    else:
                        logger.warning("No sections generated for file: %s. Skipping upload.", filename)
                        # Consider if this should count as failed or just skipped
                        failed_files += 1 # Count as failed if parsing/splitting produced nothing

                except Exception as e:
                     logger.exception("Failed to process file %s during 'Add' action: %s", filename, e)
                     failed_files += 1
                finally:
                    # Ensure file handles are closed
                    if file:
                        try:
                            file.close()
                        except Exception as close_err:
                            logger.warning("Error closing file %s: %s", filename, close_err)

            logger.info(f"FileStrategy 'Add' completed. Processed: {processed_files}, Failed/Skipped: {failed_files}, Total Files: {file_count}")

        elif self.document_action == DocumentAction.Remove:
            logger.info("Starting 'Remove' document action using FileStrategy.")
            paths = self.list_file_strategy.list_paths()
            async for path in paths:
                 # SearchManager.remove_content uses 'sourcefile' which is handled correctly now
                 await self.search_manager.remove_content(path)
                 if self.blob_manager:
                     try:
                         await self.blob_manager.remove_blob(path)
                     except Exception as blob_rem_err:
                          logger.error("Failed to remove blob for path %s: %s", path, blob_rem_err)

        elif self.document_action == DocumentAction.RemoveAll:
            logger.info("Starting 'RemoveAll' document action using FileStrategy.")
            await self.search_manager.remove_content() # Remove all content from index
            if self.blob_manager:
                try:
                    await self.blob_manager.remove_blob() # Remove all blobs from container
                except Exception as blob_rem_all_err:
                     logger.error("Failed to remove all blobs: %s", blob_rem_all_err)

# Note: UploadUserFileStrategy might need similar modifications if used,
# specifically around calling parse_file and ensuring Section IDs are generated.

class UploadUserFileStrategy:
    """
    Strategy for ingesting a file that has already been uploaded to a ADLS2 storage account
    """

    def __init__(
        self,
        search_info: SearchInfo,
        file_processors: dict[str, FileProcessor],
        embeddings: Optional[OpenAIEmbeddings] = None,
        image_embeddings: Optional[ImageEmbeddings] = None,
    ):
        self.file_processors = file_processors
        self.embeddings = embeddings
        self.image_embeddings = image_embeddings
        self.search_info = search_info
        self.search_manager = SearchManager(self.search_info, None, True, False, self.embeddings)

    async def add_file(self, file: File):
        if self.image_embeddings:
            logging.warning("Image embeddings are not currently supported for the user upload feature")
        sections = await parse_file(file, self.file_processors)
        if sections:
            await self.search_manager.update_content(sections, url=file.url)

    async def remove_file(self, filename: str, oid: str):
        if filename is None or filename == "":
            logging.warning("Filename is required to remove a file")
            return
        await self.search_manager.remove_content(filename, oid)