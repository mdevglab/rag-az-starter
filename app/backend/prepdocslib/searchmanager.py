import asyncio
import logging
import os
import re
import base64
from typing import List, Optional, Dict, Any

from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
    HnswAlgorithmConfiguration,
    HnswParameters,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
    VectorSearchVectorizer,
)

from .blobmanager import BlobManager
from .embeddings import AzureOpenAIEmbeddingService, OpenAIEmbeddings
from .listfilestrategy import File
from .strategy import SearchInfo
from .textsplitter import SplitPage

logger = logging.getLogger("scripts")


class Section:
    """
    A section of a page that is stored in a search service. These sections are used as context by Azure OpenAI service
    Includes metadata handling.
    """

    def __init__(self, split_page: SplitPage, content: File, category: Optional[str] = None):
        self.split_page = split_page
        self.content = content
        self.category = category
        self.metadata: Dict[str, Any] = {}
        self.id: Optional[str] = None
        # Store filename and URL for easier access
        self.filename: str = content.filename()
        # Attempt to get URL, fall back to empty string or filename if needed
        retrieved_url = getattr(content, 'url', None) # Get 'url' attribute, default to None if absent
        if callable(retrieved_url):
            try:
                self.url = retrieved_url() # Call it if it's a method
            except Exception as e:
                logger.warning(f"Error calling url() method for file {self.filename}: {e}. Falling back to filename.")
                self.url = self.filename # Fallback on error
        elif isinstance(retrieved_url, str):
             self.url = retrieved_url # Use it directly if it's already a string
        else:
             # If retrieved_url is None or some other non-callable/non-string type, fallback to filename
             self.url = self.filename
        # Ensure URL is never None if filename is valid
        self.url = self.url or self.filename

    def create_section_id(self, section_index: int) -> str:
        """Creates a unique, URL-safe ID for this section."""
        # Use URL if available and seems more stable, otherwise filename
        source_id = self.url or self.filename
        # Basic cleaning and replace non-alphanum characters (excluding hyphen needed for structure)
        filename_safe = re.sub(r'[^\w\-]+', '_', os.path.basename(source_id)) # Use basename

        # Construct the core ID string
        id_str = f"{filename_safe}-page{self.split_page.page_num}-s{section_index}"

        # Base64 encode for safety and length, remove padding
        try:
            self.id = base64.urlsafe_b64encode(id_str.encode()).decode().rstrip("=")
        except Exception as e:
             logger.warning("Failed to generate base64 ID for '%s', using plain ID. Error: %s", id_str, e)
             # Fallback to a simpler, potentially less safe ID if encoding fails
             self.id = id_str[:512] # Limit length as fallback

        return self.id

    def to_search_dict(self, use_image_sourcepage: bool = False) -> Dict[str, Any]:
        """
        Converts the section into a dictionary suitable for Azure Search upload,
        incorporating metadata.
        """
        if not self.id:
             raise ValueError("Section ID must be set before calling to_search_dict.")

        # Determine sourcepage value based on whether image embeddings are used
        if use_image_sourcepage:
             sourcepage_val = BlobManager.blob_image_name_from_file_page(
                 filename=self.filename, page=self.split_page.page_num
             )
        else:
             sourcepage_val = BlobManager.sourcepage_from_file_page(
                 filename=self.filename, page=self.split_page.page_num
             )

        # --- Core document fields ---
        doc = {
            "id": self.id,
            "content": self.split_page.text,
            "category": self.category,
            "sourcepage": sourcepage_val,
             # *** CRITICAL: Use metadata 'sourcefile' if present, else fallback ***
            "sourcefile": self.metadata.get("sourcefile", self.filename), # Default to filename if no metadata
             # Add ACLs if they exist on the content object
            **(getattr(self.content, 'acls', {})), # Use getattr for safety
             # Add storageUrl if available from URL
             "storageUrl": self.url if self.url != self.filename else None # Only set if different from filename
        }

        # --- Merge additional metadata ---
        # Add other fields from metadata, avoiding overwrite of core fields defined above
        # This assumes the index schema might have corresponding fields.
        for key, value in self.metadata.items():
            if key not in doc and key != "sourcefile": # Avoid overwriting and redundant 'sourcefile'
                doc[key] = value
                logger.debug("Added metadata key '%s' to search doc for ID %s", key, self.id)

        # Filter out None values before returning
        return {k: v for k, v in doc.items() if v is not None}


class SearchManager:
    """
    Class to manage a search service. It can create indexes, and update or remove sections stored in these indexes
    To learn more, please visit https://learn.microsoft.com/azure/search/search-what-is-azure-search
    """

    def __init__(
        self,
        search_info: SearchInfo,
        search_analyzer_name: Optional[str] = None,
        use_acls: bool = False,
        use_int_vectorization: bool = False,
        embeddings: Optional[OpenAIEmbeddings] = None,
        search_images: bool = False,
    ):
        self.search_info = search_info
        self.search_analyzer_name = search_analyzer_name
        self.use_acls = use_acls
        self.use_int_vectorization = use_int_vectorization
        self.embeddings = embeddings
        # Integrated vectorization uses the ada-002 model with 1536 dimensions
        self.embedding_dimensions = self.embeddings.open_ai_dimensions if self.embeddings else 1536
        self.search_images = search_images

    async def create_index(self, vectorizers: Optional[List[VectorSearchVectorizer]] = None):

        # If you expect *other* metadata fields from JSON (beyond url -> sourcefile),
        # you would need to add corresponding SimpleField definitions here.
        logger.info("Checking whether search index %s exists...", self.search_info.index_name)

        async with self.search_info.create_search_index_client() as search_index_client:

            if self.search_info.index_name not in [name async for name in search_index_client.list_index_names()]:
                logger.info("Creating new search index %s", self.search_info.index_name)
                fields = [
                    (
                        SimpleField(name="id", type="Edm.String", key=True)
                        if not self.use_int_vectorization
                        else SearchField(
                            name="id",
                            type="Edm.String",
                            key=True,
                            sortable=True,
                            filterable=True,
                            facetable=True,
                            analyzer_name="keyword",
                        )
                    ),
                    SearchableField(
                        name="content",
                        type="Edm.String",
                        analyzer_name=self.search_analyzer_name,
                    ),
                    SearchField(
                        name="embedding",
                        type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                        hidden=False,
                        searchable=True,
                        filterable=False,
                        sortable=False,
                        facetable=False,
                        vector_search_dimensions=self.embedding_dimensions,
                        vector_search_profile_name="embedding_config",
                    ),
                    SimpleField(name="category", type="Edm.String", filterable=True, facetable=True),
                    SimpleField(
                        name="sourcepage",
                        type="Edm.String",
                        filterable=True,
                        facetable=True,
                    ),
                    SimpleField(
                        name="sourcefile",
                        type="Edm.String",
                        filterable=True,
                        facetable=True,
                    ),
                    SimpleField(
                        name="storageUrl",
                        type="Edm.String",
                        filterable=True,
                        facetable=False,
                    ),
                    # --- ADD NEW FIELD DEFINITION for updatedate ---
                    SimpleField(
                        name="updatedate", # The name must match the key used in the metadata dictionary
                        type="Edm.String", # Assuming string storage from JSON
                        retrievable=True,
                        filterable=True,
                        sortable=True,  # Useful for sorting by date
                        facetable=True   # Useful for faceting by date
                    ),
                ]
                if self.use_acls:
                    fields.append(
                        SimpleField(
                            name="oids",
                            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
                            filterable=True,
                        )
                    )
                    fields.append(
                        SimpleField(
                            name="groups",
                            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
                            filterable=True,
                        )
                    )
                if self.use_int_vectorization:
                    logger.info("Including parent_id field in new index %s", self.search_info.index_name)
                    fields.append(SearchableField(name="parent_id", type="Edm.String", filterable=True))
                if self.search_images:
                    logger.info("Including imageEmbedding field in new index %s", self.search_info.index_name)
                    fields.append(
                        SearchField(
                            name="imageEmbedding",
                            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                            hidden=False,
                            searchable=True,
                            filterable=False,
                            sortable=False,
                            facetable=False,
                            vector_search_dimensions=1024,
                            vector_search_profile_name="embedding_config",
                        ),
                    )

                vectorizers = []
                if self.embeddings and isinstance(self.embeddings, AzureOpenAIEmbeddingService):
                    logger.info(
                        "Including vectorizer for search index %s, using Azure OpenAI service %s",
                        self.search_info.index_name,
                        self.embeddings.open_ai_service,
                    )
                    vectorizers.append(
                        AzureOpenAIVectorizer(
                            vectorizer_name=f"{self.search_info.index_name}-vectorizer",
                            parameters=AzureOpenAIVectorizerParameters(
                                resource_url=self.embeddings.open_ai_endpoint,
                                deployment_name=self.embeddings.open_ai_deployment,
                                model_name=self.embeddings.open_ai_model_name,
                            ),
                        )
                    )
                else:
                    logger.info(
                        "Not including vectorizer for search index %s, no Azure OpenAI service found",
                        self.search_info.index_name,
                    )

                index = SearchIndex(
                    name=self.search_info.index_name,
                    fields=fields,
                    semantic_search=SemanticSearch(
                        configurations=[
                            SemanticConfiguration(
                                name="default",
                                prioritized_fields=SemanticPrioritizedFields(
                                    title_field=None, content_fields=[SemanticField(field_name="content")]
                                ),
                            )
                        ]
                    ),
                    vector_search=VectorSearch(
                        algorithms=[
                            HnswAlgorithmConfiguration(
                                name="hnsw_config",
                                parameters=HnswParameters(metric="cosine"),
                            )
                        ],
                        profiles=[
                            VectorSearchProfile(
                                name="embedding_config",
                                algorithm_configuration_name="hnsw_config",
                                vectorizer_name=(
                                    f"{self.search_info.index_name}-vectorizer" if self.use_int_vectorization else None
                                ),
                            ),
                        ],
                        vectorizers=vectorizers,
                    ),
                )

                await search_index_client.create_index(index)
            else:
                logger.info("Search index %s already exists", self.search_info.index_name)
                existing_index = await search_index_client.get_index(self.search_info.index_name)

                field_exists = any(field.name == "updatedate" for field in existing_index.fields)
                if not field_exists:
                    logger.info("Adding 'updatedate' field to existing index %s", self.search_info.index_name)
                    existing_index.fields.append(
                         SimpleField(name="updatedate", type="Edm.String", retrievable=True, filterable=True, sortable=True, facetable=True)
                    )

                if not any(field.name == "storageUrl" for field in existing_index.fields):
                    logger.info("Adding storageUrl field to index %s", self.search_info.index_name)
                    existing_index.fields.append(
                        SimpleField(
                            name="storageUrl",
                            type="Edm.String",
                            filterable=True,
                            facetable=False,
                        ),
                    )
                    await search_index_client.create_or_update_index(existing_index)

                if existing_index.vector_search is not None and (
                    existing_index.vector_search.vectorizers is None
                    or len(existing_index.vector_search.vectorizers) == 0
                ):
                    if self.embeddings is not None and isinstance(self.embeddings, AzureOpenAIEmbeddingService):
                        logger.info("Adding vectorizer to search index %s", self.search_info.index_name)
                        existing_index.vector_search.vectorizers = [
                            AzureOpenAIVectorizer(
                                vectorizer_name=f"{self.search_info.index_name}-vectorizer",
                                parameters=AzureOpenAIVectorizerParameters(
                                    resource_url=self.embeddings.open_ai_endpoint,
                                    deployment_name=self.embeddings.open_ai_deployment,
                                    model_name=self.embeddings.open_ai_model_name,
                                ),
                            )
                        ]
                        await search_index_client.create_or_update_index(existing_index)
                    else:
                        logger.info(
                            "Can't add vectorizer to search index %s since no Azure OpenAI embeddings service is defined",
                            self.search_info,
                        )

    async def update_content(
        self, sections: List[Section], image_embeddings: Optional[List[List[float]]] = None, url: Optional[str] = None # Keep url for potential backward compat or explicit override? Let's ignore it for now as Section handles url.
    ):
        MAX_BATCH_SIZE = 1000
        section_batches = [sections[i : i + MAX_BATCH_SIZE] for i in range(0, len(sections), MAX_BATCH_SIZE)]
        batch_num = 0

# Example Usage (Conceptual - not part of the class itself)
# async def main_example():
#     # ... setup search_info, embeddings ...
#     manager = SearchManager(search_info, embeddings=embeddings)
#     # ... create SplitPage, File objects ...
#     split_page1 = SplitPage(page_num=0, text="This is content from page 0.")
#     # Create a mock File object
#     class MockFile:
#         def __init__(self, name, url=None):
#             self._filename = name
#             self._url = url or name
#             self.acls = {"oids": ["oid1"], "groups": ["group1"]} # Example ACLs
#         def filename(self): return self._filename
#         def url(self): return self._url
#
#     file_obj = MockFile("data/my_document.json", url="https://example.com/data/my_document.json")
#
#     section1 = Section(split_page1, content=file_obj, category="Test")
#     # *** Add metadata ***
#     section1.metadata = {"sourcefile": "https://real.origin.com/path/to/original.json", "custom_field": "value1"}
#
#     # Update content requires a list
#     await manager.update_content([section1])


        async with self.search_info.create_search_client() as search_client:
            for batch_index, batch in enumerate(section_batches):
                batch_num += 1
                logger.info("Processing batch %d of %d sections...", batch_num, len(batch))
                documents = [] # List to hold final dictionaries for this batch

                # 1. Generate IDs and base search dictionaries using Section method
                base_documents = []
                texts_for_embedding = []
                try:
                    for section_index, section in enumerate(batch):
                        # Generate the unique ID first
                        section.create_section_id(section_index=section_index + batch_index * MAX_BATCH_SIZE)
                        # Create the base dictionary using the section's data and metadata
                        base_doc = section.to_search_dict(use_image_sourcepage=(image_embeddings is not None))
                        base_documents.append(base_doc)
                        texts_for_embedding.append(section.split_page.text)
                except Exception as e:
                    logger.exception("Error creating base search document in batch %d: %s. Skipping batch.", batch_num, e)
                    continue # Skip this batch if dict creation fails

                # 2. Calculate Embeddings (if applicable)
                if self.embeddings and texts_for_embedding:
                    try:
                        logger.debug("Calculating text embeddings for batch %d (%d texts)", batch_num, len(texts_for_embedding))
                        embeddings = await self.embeddings.create_embeddings(texts=texts_for_embedding)
                        if len(embeddings) != len(base_documents):
                             logger.error("Mismatch between embeddings count (%d) and document count (%d) in batch %d. Skipping embedding assignment.",
                                          len(embeddings), len(base_documents), batch_num)
                        else:
                             # Add embeddings to the dictionaries
                             for i, doc in enumerate(base_documents):
                                 doc["embedding"] = embeddings[i]
                    except Exception as e:
                         logger.exception("Error calculating text embeddings for batch %d: %s. Documents will be uploaded without embeddings.", batch_num, e)


                # 3. Add Image Embeddings (if applicable)
                if image_embeddings:
                    logger.debug("Assigning image embeddings for batch %d", batch_num)
                    # Need to map page_num from section back to the image_embeddings list index
                    for i, section in enumerate(batch):
                        try:
                            # Check bounds for safety
                            if 0 <= section.split_page.page_num < len(image_embeddings):
                                if i < len(base_documents): # Ensure doc exists
                                     base_documents[i]["imageEmbedding"] = image_embeddings[section.split_page.page_num]
                            else:
                                logger.warning("Page number %d out of bounds for image embeddings list (length %d) for section ID %s",
                                             section.split_page.page_num, len(image_embeddings), base_documents[i].get("id", "N/A"))
                        except IndexError:
                             logger.warning("Index error assigning image embedding for page %d (section ID %s)",
                                          section.split_page.page_num, base_documents[i].get("id", "N/A"))
                        except Exception as e:
                            logger.exception("Error assigning image embedding for section ID %s: %s", base_documents[i].get("id", "N/A"), e)


                # 4. Upload the prepared documents
                if base_documents:
                    try:
                        logger.info("Uploading %d documents for batch %d...", len(base_documents), batch_num)
                        await search_client.upload_documents(documents=base_documents)
                        logger.info("Successfully uploaded batch %d.", batch_num)
                    except Exception as e:
                        # Log the error but continue to the next batch if possible
                        logger.exception("Error uploading documents for batch %d: %s", batch_num, e)
                else:
                     logger.warning("No documents generated for batch %d, skipping upload.", batch_num)
        # async with self.search_info.create_search_client() as search_client:
        #     for batch_index, batch in enumerate(section_batches):
        #         documents = [
        #             {
        #                 "id": f"{section.content.filename_to_id()}-page-{section_index + batch_index * MAX_BATCH_SIZE}",
        #                 "content": section.split_page.text,
        #                 "category": section.category,
        #                 "sourcepage": (
        #                     BlobManager.blob_image_name_from_file_page(
        #                         filename=section.content.filename(),
        #                         page=section.split_page.page_num,
        #                     )
        #                     if image_embeddings
        #                     else BlobManager.sourcepage_from_file_page(
        #                         filename=section.content.filename(),
        #                         page=section.split_page.page_num,
        #                     )
        #                 ),
        #                 "sourcefile": section.content.filename(),
        #                 **section.content.acls,
        #             }
        #             for section_index, section in enumerate(batch)
        #         ]
        #         if url:
        #             for document in documents:
        #                 document["storageUrl"] = url
        #         if self.embeddings:
        #             embeddings = await self.embeddings.create_embeddings(
        #                 texts=[section.split_page.text for section in batch]
        #             )
        #             for i, document in enumerate(documents):
        #                 document["embedding"] = embeddings[i]
        #         if image_embeddings:
        #             for i, (document, section) in enumerate(zip(documents, batch)):
        #                 document["imageEmbedding"] = image_embeddings[section.split_page.page_num]

        #         await search_client.upload_documents(documents)

    async def remove_content(self, path: Optional[str] = None, only_oid: Optional[str] = None):
        logger.info(
            f"Removing sections for path '{path or '<all>'}' using OID filter '{only_oid or '<none>'}' from search index '{self.search_info.index_name}'"
        )
        async with self.search_info.create_search_client() as search_client:
            while True:
                filter = None
                if path is not None:
                    # Replace ' with '' to escape the single quote for the filter
                    # https://learn.microsoft.com/azure/search/query-odata-filter-orderby-syntax#escaping-special-characters-in-string-constants
                    path_for_filter = os.path.basename(path).replace("'", "''")
                    filter = f"sourcefile eq '{path_for_filter}'"
                max_results = 1000
                result = await search_client.search(
                    search_text="", filter=filter, top=max_results, include_total_count=True
                )
                result_count = await result.get_count()
                if result_count == 0:
                    break
                documents_to_remove = []
                async for document in result:
                    # If only_oid is set, only remove documents that have only this oid
                    if not only_oid or document.get("oids") == [only_oid]:
                        documents_to_remove.append({"id": document["id"]})
                if len(documents_to_remove) == 0:
                    if result_count < max_results:
                        break
                    else:
                        continue
                removed_docs = await search_client.delete_documents(documents_to_remove)
                logger.info("Removed %d sections from index", len(removed_docs))
                # It can take a few seconds for search results to reflect changes, so wait a bit
                await asyncio.sleep(2)
