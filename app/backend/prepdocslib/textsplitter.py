import logging
from abc import ABC
from typing import Generator, List

import tiktoken

from .page import Page, SplitPage

logger = logging.getLogger("scripts")


class TextSplitter(ABC):
    """
    Splits a list of pages into smaller chunks
    :param pages: The pages to split
    :return: A generator of SplitPage
    """

    def split_pages(self, pages: List[Page]) -> Generator[SplitPage, None, None]:
        if False:
            yield  # pragma: no cover - this is necessary for mypy to type check


ENCODING_MODEL = "text-embedding-ada-002"

STANDARD_WORD_BREAKS = [",", ";", ":", " ", "(", ")", "[", "]", "{", "}", "\t", "\n"]

# See W3C document https://www.w3.org/TR/jlreq/#cl-01
CJK_WORD_BREAKS = [
    "、",
    "，",
    "；",
    "：",
    "（",
    "）",
    "【",
    "】",
    "「",
    "」",
    "『",
    "』",
    "〔",
    "〕",
    "〈",
    "〉",
    "《",
    "》",
    "〖",
    "〗",
    "〘",
    "〙",
    "〚",
    "〛",
    "〝",
    "〞",
    "〟",
    "〰",
    "–",
    "—",
    "‘",
    "’",
    "‚",
    "‛",
    "“",
    "”",
    "„",
    "‟",
    "‹",
    "›",
]

STANDARD_SENTENCE_ENDINGS = [".", "!", "?"]

# See CL05 and CL06, based on JIS X 4051:2004
# https://www.w3.org/TR/jlreq/#cl-04
CJK_SENTENCE_ENDINGS = ["。", "！", "？", "‼", "⁇", "⁈", "⁉"]

# NB: text-embedding-3-XX is the same BPE as text-embedding-ada-002
bpe = tiktoken.encoding_for_model(ENCODING_MODEL)

DEFAULT_OVERLAP_PERCENT = 10  # See semantic search article for 10% overlap performance
DEFAULT_SECTION_LENGTH = 1000  # Roughly 400-500 tokens for English

# --- Tiktoken Initialization ---
# It's often better to do this setup once if possible,
# but robust initialization in __init__ is safer.
try:
    import tiktoken
    # We'll get the specific encoding in __init__
    tiktoken_found = True
    logger.info("Tiktoken library found.")
except ImportError:
    logger.warning("Tiktoken library not found. Please install it (`pip install tiktoken`) for accurate token-based splitting. Falling back to character count heuristics.")
    tiktoken_found = False
except Exception as e:
    logger.error(f"Failed during tiktoken import or initial setup: {e}")
    tiktoken_found = False # Treat other import errors as if not found

class SentenceTextSplitter(TextSplitter):
    """
    Class that splits pages into smaller chunks. This is required because embedding models may not be able to analyze an entire page at once
    """

    def __init__(self, max_tokens_per_section: int = 500):
        self.sentence_endings = STANDARD_SENTENCE_ENDINGS + CJK_SENTENCE_ENDINGS
        self.word_breaks = STANDARD_WORD_BREAKS + CJK_WORD_BREAKS
        self.max_section_length = DEFAULT_SECTION_LENGTH
        self.sentence_search_limit = 100
        self.max_tokens_per_section = max_tokens_per_section
        self.section_overlap = int(self.max_section_length * DEFAULT_OVERLAP_PERCENT / 100)
        self.bpe = None # Initialize tokenizer attribute to None

    def split_page_by_max_tokens(self, page_num: int, text: str) -> Generator[SplitPage, None, None]:
        """
        Recursively splits page by maximum number of tokens to better handle languages with higher token/word ratios.
               Fixes len() error on token generator.
        NOTE: Splitting logic is still primarily character-based after the initial check.
        """
        if not text.strip(): # Avoid processing empty strings
             return

        try:
            # --- FIX: Convert token generator to list before len() ---
            token_generator = bpe.encode(text) # Assume bpe.encode exists and works
            tokens = list(token_generator) # Convert the generator to a list
            num_tokens = len(tokens) # Now len() works on the list
            # --- END FIX ---

            logger.debug("Splitting chunk by tokens: page_num=%d, text_len=%d, num_tokens=%d, max_tokens=%d",
                         page_num, len(text), num_tokens, self.max_tokens_per_section)

            if num_tokens <= self.max_tokens_per_section:
                # Section is within max tokens, yield it
                logger.debug("Chunk is within token limit, yielding.")
                yield SplitPage(page_num=page_num, text=text)
            else:
                # Chunk exceeds max tokens, needs splitting.
                # --- Current splitting logic (CHARACTER-based) ---
                # This logic finds a split point based on sentence endings near the
                # CHARACTER midpoint. It doesn't guarantee the resulting halves
                # will be under the TOKEN limit. A truly token-aware split is harder.
                logger.debug("Chunk exceeds token limit, attempting character-based split.")
                start = int(len(text) // 2)
                pos = 0
                boundary = int(len(text) // 3) # Outer third boundary
                split_position = -1

                # Search outwards from center for sentence ending
                while start - pos > boundary or start + pos < len(text) - boundary: # Adjust loop condition slightly
                    # Check position before center
                    if start - pos >= 0 and text[start - pos] in self.sentence_endings:
                        split_position = start - pos
                        break
                    # Check position after center
                    if start + pos < len(text) and text[start + pos] in self.sentence_endings:
                        split_position = start + pos
                        break
                    pos += 1
                    # Prevent infinite loop if no sentence ending found in middle third
                    if start - pos < boundary and start + pos >= len(text) - boundary:
                        logger.debug("No sentence boundary found in middle third, will perform midpoint split.")
                        break


                if split_position > 0:
                    logger.debug("Found sentence boundary split point at char %d", split_position)
                    first_half = text[: split_position + 1]
                    # Ensure second half starts after the boundary character
                    second_half_start = split_position + 1
                    while second_half_start < len(text) and text[second_half_start].isspace():
                         second_half_start += 1 # Skip leading whitespace
                    second_half = text[second_half_start :]

                else:
                    # No sentence boundary found reasonably close, split near middle with overlap
                    logger.debug("Splitting near character midpoint with overlap.")
                    middle = int(len(text) // 2)
                    # Calculate overlap based on tokens or characters? Sticking to characters for now.
                    overlap_chars = int(len(text) * (DEFAULT_OVERLAP_PERCENT / 100))
                    # Ensure overlap doesn't exceed half the length
                    overlap_chars = min(overlap_chars, middle // 2)

                    first_half = text[: middle + overlap_chars]
                    second_half = text[middle - overlap_chars :]

                # Recursively split the halves
                # These recursive calls will again check token counts for the smaller chunks
                if first_half.strip():
                    yield from self.split_page_by_max_tokens(page_num, first_half)
                if second_half.strip():
                    yield from self.split_page_by_max_tokens(page_num, second_half)

        except Exception as e:
             # Add logging for errors within this potentially complex function
             logger.error("Error during split_page_by_max_tokens for page %d: %s", page_num, e)
             # Decide if you want to yield the original text on error, or just stop
             # yield SplitPage(page_num=page_num, text=text) # Option: yield original on error
             # raise # Option: re-raise the exception


    def split_pages(self, pages: List[Page]) -> Generator[SplitPage, None, None]:
        def find_page(offset):
            num_pages = len(pages)
            for i in range(num_pages - 1):
                if offset >= pages[i].offset and offset < pages[i + 1].offset:
                    return pages[i].page_num
            return pages[num_pages - 1].page_num

        all_text = "".join(page.text for page in pages)
        if len(all_text.strip()) == 0:
            return

        length = len(all_text)
        if length <= self.max_section_length:
            yield from self.split_page_by_max_tokens(page_num=find_page(0), text=all_text)
            return

        start = 0
        end = length
        while start + self.section_overlap < length:
            last_word = -1
            end = start + self.max_section_length

            if end > length:
                end = length
            else:
                # Try to find the end of the sentence
                while (
                    end < length
                    and (end - start - self.max_section_length) < self.sentence_search_limit
                    and all_text[end] not in self.sentence_endings
                ):
                    if all_text[end] in self.word_breaks:
                        last_word = end
                    end += 1
                if end < length and all_text[end] not in self.sentence_endings and last_word > 0:
                    end = last_word  # Fall back to at least keeping a whole word
            if end < length:
                end += 1

            # Try to find the start of the sentence or at least a whole word boundary
            last_word = -1
            while (
                start > 0
                and start > end - self.max_section_length - 2 * self.sentence_search_limit
                and all_text[start] not in self.sentence_endings
            ):
                if all_text[start] in self.word_breaks:
                    last_word = start
                start -= 1
            if all_text[start] not in self.sentence_endings and last_word > 0:
                start = last_word
            if start > 0:
                start += 1

            section_text = all_text[start:end]
            yield from self.split_page_by_max_tokens(page_num=find_page(start), text=section_text)

            last_figure_start = section_text.rfind("<figure")
            if last_figure_start > 2 * self.sentence_search_limit and last_figure_start > section_text.rfind(
                "</figure"
            ):
                # If the section ends with an unclosed figure, we need to start the next section with the figure.
                start = min(end - self.section_overlap, start + last_figure_start)
                logger.info(
                    f"Section ends with unclosed figure, starting next section with the figure at page {find_page(start)} offset {start} figure start {last_figure_start}"
                )
            else:
                start = end - self.section_overlap

        if start + self.section_overlap < end:
            yield from self.split_page_by_max_tokens(page_num=find_page(start), text=all_text[start:end])


class SimpleTextSplitter(TextSplitter):
    """
    Class that splits pages into smaller chunks based on a max object length. It is not aware of the content of the page.
    This is required because embedding models may not be able to analyze an entire page at once
    """

    def __init__(self, max_object_length: int = 1000):
        self.max_object_length = max_object_length

    def split_pages(self, pages: List[Page]) -> Generator[SplitPage, None, None]:
        all_text = "".join(page.text for page in pages)
        if len(all_text.strip()) == 0:
            return

        length = len(all_text)
        if length <= self.max_object_length:
            yield SplitPage(page_num=0, text=all_text)
            return

        # its too big, so we need to split it
        for i in range(0, length, self.max_object_length):
            yield SplitPage(page_num=i // self.max_object_length, text=all_text[i : i + self.max_object_length])
        return
