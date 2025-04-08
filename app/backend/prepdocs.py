import argparse
import asyncio
import logging
import os
from typing import Optional, Union, Dict 

from azure.core.credentials import AzureKeyCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import AzureDeveloperCliCredential, get_bearer_token_provider
from rich.logging import RichHandler

from load_azd_env import load_azd_env
from prepdocslib.blobmanager import BlobManager
from prepdocslib.csvparser import CsvParser
from prepdocslib.embeddings import (
    AzureOpenAIEmbeddingService,
    ImageEmbeddings,
    OpenAIEmbeddingService,
    OpenAIEmbeddings, # Ensure OpenAIEmbeddings base/type is imported if needed for type hints
)
from prepdocslib.fileprocessor import FileProcessor
from prepdocslib.filestrategy import FileStrategy
from prepdocslib.htmlparser import LocalHTMLParser
from prepdocslib.integratedvectorizerstrategy import (
    IntegratedVectorizerStrategy,
)
#from prepdocslib.jsonparser import JsonParser
from prepdocslib.customjsonparser import SpecificJsonParser

from prepdocslib.listfilestrategy import (
    ADLSGen2ListFileStrategy,
    ListFileStrategy,
    LocalListFileStrategy,
)
from prepdocslib.parser import Parser
from prepdocslib.pdfparser import DocumentAnalysisParser, LocalPdfParser
from prepdocslib.strategy import DocumentAction, SearchInfo, Strategy
from prepdocslib.textparser import TextParser
from prepdocslib.textsplitter import SentenceTextSplitter, SimpleTextSplitter

logger = logging.getLogger("scripts")


def clean_key_if_exists(key: Union[str, None]) -> Union[str, None]:
    """Remove leading and trailing whitespace from a key if it exists. If the key is empty, return None."""
    if key is not None and key.strip() != "":
        return key.strip()
    return None


async def setup_search_info(
    search_service: str, index_name: str, azure_credential: AsyncTokenCredential, search_key: Union[str, None] = None
) -> SearchInfo:
    search_creds: Union[AsyncTokenCredential, AzureKeyCredential] = (
        azure_credential if search_key is None else AzureKeyCredential(search_key)
    )

    return SearchInfo(
        endpoint=f"https://{search_service}.search.windows.net/",
        credential=search_creds,
        index_name=index_name,
    )


def setup_blob_manager(
    azure_credential: AsyncTokenCredential,
    storage_account: str,
    storage_container: str,
    storage_resource_group: str,
    subscription_id: str,
    search_images: bool,
    storage_key: Union[str, None] = None,
):
    storage_creds: Union[AsyncTokenCredential, str] = azure_credential if storage_key is None else storage_key
    return BlobManager(
        endpoint=f"https://{storage_account}.blob.core.windows.net",
        container=storage_container,
        account=storage_account,
        credential=storage_creds,
        resourceGroup=storage_resource_group,
        subscriptionId=subscription_id,
        store_page_images=search_images,
    )


def setup_list_file_strategy(
    azure_credential: AsyncTokenCredential,
    local_files: Union[str, None],
    datalake_storage_account: Union[str, None],
    datalake_filesystem: Union[str, None],
    datalake_path: Union[str, None],
    datalake_key: Union[str, None],
):
    list_file_strategy: ListFileStrategy
    if datalake_storage_account:
        if datalake_filesystem is None or datalake_path is None:
            raise ValueError("DataLake file system and path are required when using Azure Data Lake Gen2")
        adls_gen2_creds: Union[AsyncTokenCredential, str] = azure_credential if datalake_key is None else datalake_key
        logger.info("Using Data Lake Gen2 Storage Account: %s", datalake_storage_account)
        list_file_strategy = ADLSGen2ListFileStrategy(
            data_lake_storage_account=datalake_storage_account,
            data_lake_filesystem=datalake_filesystem,
            data_lake_path=datalake_path,
            credential=adls_gen2_creds,
        )
    elif local_files:
        logger.info("Using local files: %s", local_files)
        list_file_strategy = LocalListFileStrategy(path_pattern=local_files)
    else:
        raise ValueError("Either local_files or datalake_storage_account must be provided.")
    return list_file_strategy


def setup_embeddings_service(
    azure_credential: AsyncTokenCredential,
    openai_host: str,
    openai_model_name: str,
    openai_service: Union[str, None],
    openai_custom_url: Union[str, None],
    openai_deployment: Union[str, None],
    openai_dimensions: int,
    openai_api_version: str,
    openai_key: Union[str, None],
    openai_org: Union[str, None],
    disable_vectors: bool = False,
    disable_batch_vectors: bool = False,
):
    if disable_vectors:
        logger.info("Not setting up embeddings service")
        return None

    if openai_host != "openai":
        azure_open_ai_credential: Union[AsyncTokenCredential, AzureKeyCredential] = (
            azure_credential if openai_key is None else AzureKeyCredential(openai_key)
        )
        return AzureOpenAIEmbeddingService(
            open_ai_service=openai_service,
            open_ai_custom_url=openai_custom_url,
            open_ai_deployment=openai_deployment,
            open_ai_model_name=openai_model_name,
            open_ai_dimensions=openai_dimensions,
            open_ai_api_version=openai_api_version,
            credential=azure_open_ai_credential,
            disable_batch=disable_batch_vectors,
        )
    else:
        if openai_key is None:
            raise ValueError("OpenAI key is required when using the non-Azure OpenAI API")
        return OpenAIEmbeddingService(
            open_ai_model_name=openai_model_name,
            open_ai_dimensions=openai_dimensions,
            credential=openai_key,
            organization=openai_org,
            disable_batch=disable_batch_vectors,
        )


def setup_file_processors(
    azure_credential: AsyncTokenCredential, # Keep existing args
    document_intelligence_service: Union[str, None],
    document_intelligence_key: Union[str, None] = None,
    local_pdf_parser: bool = False,
    local_html_parser: bool = False,
    search_images: bool = False, # Keep search_images if needed by DI parser
    use_content_understanding: bool = False, # Keep CU params if needed by DI parser
    content_understanding_endpoint: Union[str, None] = None,
    # --- ADD parameter for the metadata field name ---
    json_metadata_field: str = "sourcefile"
) -> Dict[str, FileProcessor]:
    """Configures and returns a dictionary of file processors."""

    # Choose appropriate splitters
    sentence_text_splitter = SentenceTextSplitter()
    simple_text_splitter = SimpleTextSplitter() # Good for CSV, maybe simple JSON content if needed

    # Setup Document Intelligence parser (if configured)
    doc_int_parser: Optional[DocumentAnalysisParser] = None
    if document_intelligence_service:
        # ... (doc intel setup logic as before) ...
        documentintelligence_creds: Union[AsyncTokenCredential, AzureKeyCredential] = (
            azure_credential if document_intelligence_key is None else AzureKeyCredential(document_intelligence_key)
        )
        doc_int_parser = DocumentAnalysisParser(
            endpoint=f"https://{document_intelligence_service}.cognitiveservices.azure.com/",
            credential=documentintelligence_creds,
            use_content_understanding=use_content_understanding,
            content_understanding_endpoint=content_understanding_endpoint,
        )


    # Setup PDF parser (prefer DI if available, fallback to local)
    pdf_parser: Optional[Parser] = None
    if doc_int_parser:
        pdf_parser = doc_int_parser
    elif local_pdf_parser:
        pdf_parser = LocalPdfParser()
    else: # Neither DI nor local explicitly enabled
        logger.warning("No PDF parser configured (Document Intelligence not specified, USE_LOCAL_PDF_PARSER not true). PDFs will be skipped.")


    # Setup HTML parser (prefer DI if available, fallback to local)
    html_parser: Optional[Parser] = None
    if doc_int_parser:
         html_parser = doc_int_parser
    elif local_html_parser:
        html_parser = LocalHTMLParser()
    else:
         logger.warning("No HTML parser configured (Document Intelligence not specified, USE_LOCAL_HTML_PARSER not true). HTML files will be skipped.")


    # Initialize the dictionary of file processors
    file_processors: Dict[str, FileProcessor] = {}

    # --- ADD Specific JSON Parser ---
    # Use the custom parser for .json files, mapping 'url' to the specified metadata field.
    # SentenceTextSplitter is generally better for natural language found in 'content'.
    logger.info("Registering SpecificJsonParser for .json files, mapping 'url' to '%s'", json_metadata_field)
    file_processors[".json"] = FileProcessor(
        SpecificJsonParser(metadata_field_name=json_metadata_field),
        sentence_text_splitter
    )

    # Add standard text-based formats
    file_processors[".md"] = FileProcessor(TextParser(), sentence_text_splitter)
    file_processors[".txt"] = FileProcessor(TextParser(), sentence_text_splitter)
    # Use simple splitter for CSV as structure is tabular, not sentential
    file_processors[".csv"] = FileProcessor(CsvParser(), simple_text_splitter)

    # Add PDF processor if configured
    if pdf_parser:
        file_processors[".pdf"] = FileProcessor(pdf_parser, sentence_text_splitter)

    # Add HTML processor if configured
    if html_parser:
        file_processors[".html"] = FileProcessor(html_parser, sentence_text_splitter)

    # Add Document Intelligence handled types (if DI is configured)
    if doc_int_parser:
        di_formats = {
            ".docx", ".pptx", ".xlsx", # Office formats
            ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".heic" # Image formats
        }
        for ext in di_formats:
            # Use sentence splitter for text extracted from these formats
            file_processors[ext] = FileProcessor(doc_int_parser, sentence_text_splitter)

    logger.info("Registered file processors for extensions: %s", list(file_processors.keys()))
    return file_processors



def setup_image_embeddings_service(
    azure_credential: AsyncTokenCredential, vision_endpoint: Union[str, None], search_images: bool
) -> Union[ImageEmbeddings, None]:
    image_embeddings_service: Optional[ImageEmbeddings] = None
    if search_images:
        if vision_endpoint is None:
            raise ValueError("A computer vision endpoint is required when GPT-4-vision is enabled.")
        image_embeddings_service = ImageEmbeddings(
            endpoint=vision_endpoint,
            token_provider=get_bearer_token_provider(azure_credential, "https://cognitiveservices.azure.com/.default"),
        )
    return image_embeddings_service


async def main(strategy: Strategy, setup_index: bool = True):
    if setup_index:
        await strategy.setup()

    await strategy.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Prepare documents by extracting content from PDFs, splitting content into sections, uploading to blob storage, and indexing in a search index."
    )
    parser.add_argument("files", nargs="?", help="Files to be processed")

    parser.add_argument(
        "--category", help="Value for the category field in the search index for all sections indexed in this run"
    )
    parser.add_argument(
        "--skipblobs", action="store_true", help="Skip uploading individual pages to Azure Blob Storage"
    )
    parser.add_argument(
        "--disablebatchvectors", action="store_true", help="Don't compute embeddings in batch for the sections"
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help="Remove references to this document from blob storage and the search index",
    )
    parser.add_argument(
        "--removeall",
        action="store_true",
        help="Remove all blobs from blob storage and documents from the search index",
    )

    # Optional key specification:
    parser.add_argument(
        "--searchkey",
        required=False,
        help="Optional. Use this Azure AI Search account key instead of the current user identity to login (use az login to set current user for Azure)",
    )
    parser.add_argument(
        "--storagekey",
        required=False,
        help="Optional. Use this Azure Blob Storage account key instead of the current user identity to login (use az login to set current user for Azure)",
    )
    parser.add_argument(
        "--datalakekey", required=False, help="Optional. Use this key when authenticating to Azure Data Lake Gen2"
    )
    parser.add_argument(
        "--documentintelligencekey",
        required=False,
        help="Optional. Use this Azure Document Intelligence account key instead of the current user identity to login (use az login to set current user for Azure)",
    )
    parser.add_argument(
        "--searchserviceassignedid",
        required=False,
        help="Search service system assigned Identity (Managed identity) (used for integrated vectorization)",
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    # if args.verbose:
    #     logging.basicConfig(format="%(message)s", datefmt="[%X]", handlers=[RichHandler(rich_tracebacks=True)])
    #     # We only set the level to INFO for our logger,
    #     # to avoid seeing the noisy INFO level logs from the Azure SDKs
    #     logger.setLevel(logging.DEBUG)

    # --- Logging Setup ---
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    if args.verbose:
        logging.getLogger("scripts").setLevel(logging.DEBUG) # Set specific logger to DEBUG
        logging.getLogger("prepdocslib").setLevel(logging.DEBUG) # Also enable DEBUG for the library
        # Setup RichHandler if you have it installed and prefer it for verbose mode
        # try:
        #     from rich.logging import RichHandler
        #     logging.basicConfig(level=logging.DEBUG, format="%(message)s", datefmt="[%X]", handlers=[RichHandler(rich_tracebacks=True)])
        #     logging.getLogger("scripts").setLevel(logging.DEBUG)
        #     logging.getLogger("prepdocslib").setLevel(logging.DEBUG)
        #     logger.info("Verbose logging enabled using RichHandler.")
        # except ImportError:
        #     logger.info("Verbose logging enabled (standard handler). Install 'rich' for enhanced output.")
        logger.info("Verbose logging enabled.")
    else:
        logging.getLogger("scripts").setLevel(logging.INFO)
        logging.getLogger("prepdocslib").setLevel(logging.INFO)
         # Reduce noise from Azure SDKs in non-verbose mode
        logging.getLogger("azure.core.pipeline.policies").setLevel(logging.WARNING)
        logging.getLogger("azure.identity").setLevel(logging.WARNING)
        logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)


    load_azd_env()

    if os.getenv("AZURE_PUBLIC_NETWORK_ACCESS") == "Disabled":
        logger.error("AZURE_PUBLIC_NETWORK_ACCESS is set to Disabled. Exiting.")
        exit(0)

    use_int_vectorization = os.getenv("USE_FEATURE_INT_VECTORIZATION", "").lower() == "true"
    use_gptvision = os.getenv("USE_GPT4V", "").lower() == "true"
    use_acls = os.getenv("AZURE_ADLS_GEN2_STORAGE_ACCOUNT") is not None
    dont_use_vectors = os.getenv("USE_VECTORS", "").lower() == "false"
    use_content_understanding = os.getenv("USE_MEDIA_DESCRIBER_AZURE_CU", "").lower() == "true"

    # Use the current user identity to connect to Azure services. See infra/main.bicep for role assignments.
    if tenant_id := os.getenv("AZURE_TENANT_ID"):
        logger.info("Connecting to Azure services using the azd credential for tenant %s", tenant_id)
        azd_credential = AzureDeveloperCliCredential(tenant_id=tenant_id, process_timeout=60)
    else:
        logger.info("Connecting to Azure services using the azd credential for home tenant")
        azd_credential = AzureDeveloperCliCredential(process_timeout=60)

    if args.removeall:
        document_action = DocumentAction.RemoveAll
    elif args.remove:
        document_action = DocumentAction.Remove
    else:
        document_action = DocumentAction.Add

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # --- Define Metadata Field Name for JSON ---
    # Read from environment or default to "sourcefile"
    json_url_metadata_field = os.getenv("AZURE_SEARCH_JSON_URL_FIELD", "sourcefile")
    logger.info("JSON 'url' will be mapped to Azure Search field: '%s'", json_url_metadata_field)
    try:
        search_info = loop.run_until_complete(
            setup_search_info(
                search_service=os.environ["AZURE_SEARCH_SERVICE"],
                index_name=os.environ["AZURE_SEARCH_INDEX"],
                azure_credential=azd_credential,
                search_key=clean_key_if_exists(args.searchkey),
            )
        )
        blob_manager = setup_blob_manager(
            azure_credential=azd_credential,
            storage_account=os.environ["AZURE_STORAGE_ACCOUNT"],
            storage_container=os.environ["AZURE_STORAGE_CONTAINER"],
            storage_resource_group=os.environ["AZURE_STORAGE_RESOURCE_GROUP"],
            subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
            search_images=use_gptvision,
            storage_key=clean_key_if_exists(args.storagekey),
        )
        list_file_strategy = setup_list_file_strategy(
            azure_credential=azd_credential,
            local_files=args.files,
            datalake_storage_account=os.getenv("AZURE_ADLS_GEN2_STORAGE_ACCOUNT"),
            datalake_filesystem=os.getenv("AZURE_ADLS_GEN2_FILESYSTEM"),
            datalake_path=os.getenv("AZURE_ADLS_GEN2_FILESYSTEM_PATH"),
            datalake_key=clean_key_if_exists(args.datalakekey),
        )

        openai_host = os.environ["OPENAI_HOST"]
        openai_key = None
        if os.getenv("AZURE_OPENAI_API_KEY_OVERRIDE"):
            openai_key = os.getenv("AZURE_OPENAI_API_KEY_OVERRIDE")
        elif not openai_host.startswith("azure") and os.getenv("OPENAI_API_KEY"):
            openai_key = os.getenv("OPENAI_API_KEY")

        openai_dimensions = 1536
        if os.getenv("AZURE_AI_EMBED_DIMENSIONS"):
            openai_dimensions = int(os.environ["AZURE_AI_EMBED_DIMENSIONS"])
        openai_embeddings_service = setup_embeddings_service(
            azure_credential=azd_credential,
            openai_host=openai_host,
            openai_model_name=os.environ["AZURE_AI_EMBED_MODEL_NAME"],
            openai_service=os.getenv("AZURE_AI_SERVICE_NAME"),
            openai_custom_url=os.getenv("AZURE_OPENAI_CUSTOM_URL"),
            openai_deployment=os.getenv("AZURE_AI_EMBED_DEPLOYMENT_NAME"),
            # https://learn.microsoft.com/azure/ai-services/openai/api-version-deprecation#latest-ga-api-release
            openai_api_version=os.getenv("AZURE_AI_CHAT_MODEL_VERSION") or "2024-06-01",
            openai_dimensions=openai_dimensions,
            openai_key=clean_key_if_exists(openai_key),
            openai_org=os.getenv("OPENAI_ORGANIZATION"),
            disable_vectors=dont_use_vectors,
            disable_batch_vectors=args.disablebatchvectors,
        )

        ingestion_strategy: Strategy
        if use_int_vectorization:

            if not openai_embeddings_service or not isinstance(openai_embeddings_service, AzureOpenAIEmbeddingService):
                raise Exception("Integrated vectorization strategy requires an Azure OpenAI embeddings service")

            ingestion_strategy = IntegratedVectorizerStrategy(
                search_info=search_info,
                list_file_strategy=list_file_strategy,
                blob_manager=blob_manager,
                document_action=document_action,
                embeddings=openai_embeddings_service,
                subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
                search_service_user_assigned_id=args.searchserviceassignedid,
                search_analyzer_name=os.getenv("AZURE_SEARCH_ANALYZER_NAME"),
                use_acls=use_acls,
                category=args.category,
            )
        else:
            file_processors = setup_file_processors(
                azure_credential=azd_credential,
                document_intelligence_service=os.getenv("AZURE_DOCUMENTINTELLIGENCE_SERVICE"),
                document_intelligence_key=clean_key_if_exists(args.documentintelligencekey),
                local_pdf_parser=os.getenv("USE_LOCAL_PDF_PARSER") == "true",
                local_html_parser=os.getenv("USE_LOCAL_HTML_PARSER") == "true",
                search_images=use_gptvision,
                use_content_understanding=use_content_understanding,
                content_understanding_endpoint=os.getenv("AZURE_CONTENTUNDERSTANDING_ENDPOINT"),
                # --- Pass the JSON metadata field name ---
                json_metadata_field=json_url_metadata_field
            )
            image_embeddings_service = setup_image_embeddings_service(
                azure_credential=azd_credential,
                vision_endpoint=os.getenv("AZURE_VISION_ENDPOINT"),
                search_images=use_gptvision,
            )

            ingestion_strategy = FileStrategy(
                search_info=search_info,
                list_file_strategy=list_file_strategy,
                blob_manager=blob_manager,
                file_processors=file_processors,
                document_action=document_action,
                embeddings=openai_embeddings_service,
                image_embeddings=image_embeddings_service,
                search_analyzer_name=os.getenv("AZURE_SEARCH_ANALYZER_NAME"),
                use_acls=use_acls,
                category=args.category,
                use_content_understanding=use_content_understanding,
                content_understanding_endpoint=os.getenv("AZURE_CONTENTUNDERSTANDING_ENDPOINT"),
            )
        # Determine if index setup should be skipped
        should_setup_index = not (args.remove or args.removeall)
        logger.info(f"Index setup {'enabled' if should_setup_index else 'disabled'}.")
        loop.run_until_complete(main(ingestion_strategy, setup_index=not args.remove and not args.removeall))
        loop.close()

    except Exception as e:
         logger.exception(f"An error occurred during the script execution: {e}")
         # Optionally exit with a non-zero code on error
         # exit(1)
    finally:
        # Close the loop
        loop.close()
        logger.info("Script execution finished.")