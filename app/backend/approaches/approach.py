import logging
import os
from abc import ABC
from dataclasses import dataclass, field 
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    List,
    Optional,
    TypedDict,
    cast,
)

import urllib.parse

import aiohttp
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import (
    QueryCaptionResult,
    QueryType,
    VectorizedQuery,
    VectorQuery,
)
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from approaches.promptmanager import PromptManager
from core.authentication import AuthenticationHelper

logger = logging.getLogger(__name__)

@dataclass
class Document:
    id: Optional[str]
    content: Optional[str]
    embedding: Optional[List[float]]
    image_embedding: Optional[List[float]]
    category: Optional[str]
    sourcepage: Optional[str]
    sourcefile: Optional[str]
    updatedate: Optional[str] = None
    oids: Optional[List[str]] = field(default_factory=list)
    groups: Optional[List[str]] = field(default_factory=list)
    captions: List[QueryCaptionResult] = field(default_factory=list)
    score: Optional[float] = None
    reranker_score: Optional[float] = None

    def serialize_for_results(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "embedding": Document.trim_embedding(self.embedding),
            "imageEmbedding": Document.trim_embedding(self.image_embedding),
            "category": self.category,
            "sourcepage": self.sourcepage,
            "sourcefile": self.sourcefile,
            "updatedate": self.updatedate,
            "oids": self.oids,
            "groups": self.groups,
            "captions": (
                [
                    {
                        "additional_properties": caption.additional_properties,
                        "text": caption.text,
                        "highlights": caption.highlights,
                    }
                    for caption in self.captions
                ]
                if self.captions
                else []
            ),
            "score": self.score,
            "reranker_score": self.reranker_score,
        }

    @classmethod
    def trim_embedding(cls, embedding: Optional[List[float]]) -> Optional[str]:
        """Returns a trimmed list of floats from the vector embedding."""
        if embedding:
            if len(embedding) > 2:
                # Format the embedding list to show the first 2 items followed by the count of the remaining items."""
                return f"[{embedding[0]}, {embedding[1]} ...+{len(embedding) - 2} more]"
            else:
                return str(embedding)

        return None


@dataclass
class ThoughtStep:
    title: str
    description: Optional[Any]
    props: Optional[dict[str, Any]] = None


class Approach(ABC):

    # Allows usage of non-GPT model even if no tokenizer is available for accurate token counting
    # Useful for using local small language models, for example
    ALLOW_NON_GPT_MODELS = True

    def __init__(
        self,
        search_client: SearchClient,
        openai_client: AsyncOpenAI,
        auth_helper: AuthenticationHelper,
        query_language: Optional[str],
        query_speller: Optional[str],
        embedding_deployment: Optional[str],  # Not needed for non-Azure OpenAI or for retrieval_mode="text"
        embedding_model: str,
        embedding_dimensions: int,
        openai_host: str,
        vision_endpoint: str,
        vision_token_provider: Callable[[], Awaitable[str]],
        prompt_manager: PromptManager,
        updatedate_field: Optional[str] = None,
    ):
        self.search_client = search_client
        self.openai_client = openai_client
        self.auth_helper = auth_helper
        self.query_language = query_language
        self.query_speller = query_speller
        self.embedding_deployment = embedding_deployment
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
        self.openai_host = openai_host
        self.vision_endpoint = vision_endpoint
        self.vision_token_provider = vision_token_provider
        self.prompt_manager = prompt_manager
        self.updatedate_field = updatedate_field

    def build_filter(self, overrides: dict[str, Any], auth_claims: dict[str, Any]) -> Optional[str]:
        include_category = overrides.get("include_category")
        exclude_category = overrides.get("exclude_category")
        security_filter = self.auth_helper.build_security_filters(overrides, auth_claims)
        filters = []
        if include_category:
            filters.append("category eq '{}'".format(include_category.replace("'", "''")))
        if exclude_category:
            filters.append("category ne '{}'".format(exclude_category.replace("'", "''")))
        if security_filter:
            filters.append(security_filter)
        return None if len(filters) == 0 else " and ".join(filters)

    async def search(
        self,
        top: int,
        query_text: Optional[str],
        filter: Optional[str],
        vectors: List[VectorQuery],
        use_text_search: bool,
        use_vector_search: bool,
        use_semantic_captions: bool,
        minimum_search_score: Optional[float],
        minimum_reranker_score: Optional[float],
        use_semantic_ranker: bool,
        order_by: Optional[str] = None,
        
    ) -> List[Document]:
        search_text = query_text if use_text_search else ""
        search_vectors = vectors if use_vector_search else []

        search_args = {
            "search_text": search_text,
            "vector_queries": search_vectors,
            "filter": filter,
            "top": top,
            "query_language": self.query_language,
            "query_speller": self.query_speller,
            "order_by": order_by,
        }

        try:
            if use_semantic_ranker:
                # --- >>> SAFEGUARD: Remove order_by for semantic search <<< ---
                final_order_by = search_args.pop("order_by", None) # Remove order_by key
                if final_order_by is not None:
                    logger.warning(f"order_by ('{final_order_by}') was provided but ignored because semantic search is enabled.")
                # --- >>> END SAFEGUARD <<< ---

                # Add semantic-specific args
                search_args.update({
                    "query_language": self.query_language,
                    "query_speller": self.query_speller,
                    "query_caption": "extractive|highlight-false" if use_semantic_captions else None,
                    "query_type": QueryType.SEMANTIC,
                    "semantic_configuration_name": "default",
                    "semantic_query": query_text,
                })
                logger.debug(f"Executing semantic search with args: {search_args}")
                results = await self.search_client.search(**search_args)
            else:
                # For non-semantic, order_by (if not None) remains in search_args
                logger.debug(f"Executing non-semantic search with args: {search_args}")
                results = await self.search_client.search(**search_args)

            documents = []
            async for page in results.by_page():
                async for document in page:
                    documents.append(
                        Document(
                            id=document.get("id"),
                            content=document.get("content"),
                            embedding=document.get("embedding"),
                            image_embedding=document.get("imageEmbedding"),
                            category=document.get("category"),
                            sourcepage=document.get("sourcepage"),
                            sourcefile=document.get("sourcefile"),
                            updatedate=document.get(self.updatedate_field) if self.updatedate_field else None,
                            oids=document.get("oids"),
                            groups=document.get("groups"),
                            captions=cast(List[QueryCaptionResult], document.get("@search.captions")),
                            score=document.get("@search.score"),
                            reranker_score=document.get("@search.reranker_score"),
                        )
                    )

                qualified_documents = []
                for doc in documents: # documents contains the top N items returned by search
                    passes = False
                    if use_semantic_ranker:
                        # If semantic, primarily check reranker score
                        if (doc.reranker_score or -1.0) >= (minimum_reranker_score or -1.0):
                            passes = True
                            # Optional: ALSO require a minimum base score? Usually not needed with semantic.
                            # if (doc.score or -1.0) < (minimum_search_score or -1.0):
                            #     passes = False
                    else:
                        # If not semantic, check base score
                        if (doc.score or -1.0) >= (minimum_search_score or -1.0):
                            passes = True

                    if passes:
                        qualified_documents.append(doc)
                    else:
                        # Optional: Add detailed logging here to see why docs are filtered
                        logger.debug(
                            f"Document ID {getattr(doc, 'id', 'N/A')} filtered out. "
                            f"Semantic: {use_semantic_ranker}, "
                            f"Base Score: {doc.score} (Threshold: {minimum_search_score}), "
                            f"Reranker Score: {doc.reranker_score} (Threshold: {minimum_reranker_score})."
                        )

                logger.debug(f"Search returned {len(documents)} initial documents, {len(qualified_documents)} qualified after score filtering.")

            return qualified_documents
        except Exception as e:
            logger.error(f"Error during Azure Search query with args: {search_args}", exc_info=True)
            return []

    def get_sources_content(
        self, results: List[Document], use_semantic_captions: bool, use_image_citation: bool
    ) -> list[str]:

        def nonewlines(s: str) -> str:
            return s.replace("\n", " ").replace("\r", " ")

        if use_semantic_captions:
            return [
                (self.get_citation((doc.sourcepage or ""), use_image_citation))
                + ": "
                + nonewlines(" . ".join([cast(str, c.text) for c in (doc.captions or [])]))
                for doc in results
            ]
        else:
            return [
                (self.get_citation((doc.sourcepage or ""), use_image_citation)) + ": " + nonewlines(doc.content or "")
                for doc in results
            ]
        
    def get_sources_addons(
        self, results: List[Document]
    ) -> list[str]:
        processed_sources = []
        for doc in results:
            if doc and doc.sourcefile:
                encoded_source = self.encode_last_url_segment(doc.sourcefile)
                processed_sources.append(encoded_source)
            else:
                # missing sourcefile
                processed_sources.append("")
        return processed_sources

    def get_citation(self, sourcepage: str, use_image_citation: bool) -> str:
        if use_image_citation:
            return sourcepage
        else:
            path, ext = os.path.splitext(sourcepage)
            if ext.lower() == ".png":
                page_idx = path.rfind("-")
                page_number = int(path[page_idx + 1 :])
                return f"{path[:page_idx]}.pdf#page={page_number}"

            return sourcepage
        
    def encode_last_url_segment(self, url_string: str) -> str:
        """
        Encodes only the last segment of a URL path using percent-encoding.

        Handles full URLs, relative paths, query strings, and fragments.
        If no '/' is present, the entire string (before query/fragment) is encoded.
        Mimics JavaScript's encodeURIComponent on the last path segment.

        Args:
            url_string: The URL string to process.

        Returns:
            The URL string with its last path segment URL-encoded.
        """
        if not url_string:
            return ""

        # boundaries: last slash, query start, fragment start
        last_slash_index = url_string.rfind('/')
        query_index = url_string.find('?')
        fragment_index = url_string.find('#')

        # Determine the end of the path segment to encode
        path_end_index = len(url_string)
        if query_index != -1:
            path_end_index = query_index
        if fragment_index != -1:
            path_end_index = min(path_end_index, fragment_index)

        # Isolate the parts using string slicing
        base_path = ""          # The part before the segment to encode (includes last slash)
        segment_to_encode = ""  # The actual segment text
        # The part starting from the query or fragment, or empty string
        remaining_part = url_string[path_end_index:]

        if last_slash_index == -1:
            # No slash found, the whole part before ? or # is the segment
            segment_to_encode = url_string[:path_end_index]
            base_path = ""
        else:
            # Slash found, determine the start of the segment
            segment_start_index = last_slash_index + 1

            # Ensure the segment index is strictly before the path end index
            if segment_start_index < path_end_index:
                segment_to_encode = url_string[segment_start_index:path_end_index]
            else:
                # Slash is at or after the start of query/fragment (e.g., "path/?query")
                # or string ends with "/" - nothing to encode after the slash
                segment_to_encode = "" # Handled below by encoding an empty string

            # Base path includes the slash
            base_path = url_string[:last_slash_index + 1]

        # safe='' ensures it encodes '/', '?', '&', '=', '+', etc., just like encodeURIComponent
        encoded_segment = urllib.parse.quote(segment_to_encode, safe='')

        # 5. Reconstruct the URL using an f-string for clarity
        return f"{base_path}{encoded_segment}{remaining_part}"

    async def compute_text_embedding(self, q: str):
        SUPPORTED_DIMENSIONS_MODEL = {
            "text-embedding-ada-002": False,
            "text-embedding-3-small": True,
            "text-embedding-3-large": True,
        }

        class ExtraArgs(TypedDict, total=False):
            dimensions: int

        dimensions_args: ExtraArgs = (
            {"dimensions": self.embedding_dimensions} if SUPPORTED_DIMENSIONS_MODEL[self.embedding_model] else {}
        )
        embedding = await self.openai_client.embeddings.create(
            # Azure OpenAI takes the deployment name as the model name
            model=self.embedding_deployment if self.embedding_deployment else self.embedding_model,
            input=q,
            **dimensions_args,
        )
        query_vector = embedding.data[0].embedding
        return VectorizedQuery(vector=query_vector, k_nearest_neighbors=50, fields="embedding")

    async def compute_image_embedding(self, q: str):
        endpoint = urllib.parse.urljoin(self.vision_endpoint, "computervision/retrieval:vectorizeText")
        headers = {"Content-Type": "application/json"}
        params = {"api-version": "2023-02-01-preview", "modelVersion": "latest"}
        data = {"text": q}

        headers["Authorization"] = "Bearer " + await self.vision_token_provider()

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url=endpoint, params=params, headers=headers, json=data, raise_for_status=True
            ) as response:
                json = await response.json()
                image_query_vector = json["vector"]
        return VectorizedQuery(vector=image_query_vector, k_nearest_neighbors=50, fields="imageEmbedding")

    def get_system_prompt_variables(self, override_prompt: Optional[str]) -> dict[str, str]:
        # Allows client to replace the entire prompt, or to inject into the existing prompt using >>>
        if override_prompt is None:
            return {}
        elif override_prompt.startswith(">>>"):
            return {"injected_prompt": override_prompt[3:]}
        else:
            return {"override_prompt": override_prompt}

    async def run(
        self,
        messages: list[ChatCompletionMessageParam],
        session_state: Any = None,
        context: dict[str, Any] = {},
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def run_stream(
        self,
        messages: list[ChatCompletionMessageParam],
        session_state: Any = None,
        context: dict[str, Any] = {},
    ) -> AsyncGenerator[dict[str, Any], None]:
        raise NotImplementedError
