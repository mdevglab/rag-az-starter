#!/usr/bin/env python3

import os
import json
import argparse
import tempfile
import shutil
import sys

# --- Configuration ---
INDENT_LEVEL = 2  # Set desired indentation level

def process_json_string_file(filepath):
    """
    Reads a file containing a single JSON string literal,
    extracts the inner JSON, formats it, and overwrites the original file.
    Returns True if successful, False otherwise.
    """
    print(f"Processing: {filepath}")
    original_content = None
    temp_path = None

    try:
        # 1. Read the entire file content (which is expected to be a single JSON string)
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                original_content = f.read()
        except FileNotFoundError:
            print(f"  -> Error: File not found (skipped): {filepath}")
            return False
        except IOError as e:
             print(f"  -> Error: Could not read file {filepath}: {e}")
             return False

        if not original_content:
            print(f"  -> Warning: File is empty (skipped): {filepath}")
            return True # Treat as success (nothing to do)

        # 2. First parse: Decode the outer JSON string literal
        try:
            # This turns the file content "{\"key\": \"value\"}"
            # into the Python string '{"key": "value"}'
            inner_json_string = json.loads(original_content)
            if not isinstance(inner_json_string, str):
                 # Handle cases where the file contained valid JSON, but not a *string*
                 # e.g. if the file was already correctly formatted like { "key": "value" }
                 # In this scenario, we might still want to re-format it for consistency.
                 print(f"  -> Info: File does not contain a string literal, attempting direct format.")
                 # We can try parsing the original content directly as JSON object/array
                 try:
                     data = json.loads(original_content) # Try parsing original content directly
                     # If successful, proceed to formatting step below
                 except json.JSONDecodeError:
                      # If direct parsing also fails, then it's neither a valid JSON string nor valid JSON object/array
                      print(f"  -> Error: File content is neither a valid JSON string literal nor a direct JSON object/array.")
                      return False

            else:
                # 3. Second parse: Parse the JSON structure *inside* the decoded string
                try:
                    # This turns the Python string '{"key": "value"}'
                    # into the Python dict {'key': 'value'}
                    data = json.loads(inner_json_string)
                except json.JSONDecodeError as e:
                    print(f"  -> Error: Invalid JSON structure inside the string literal in {filepath}: {e}")
                    print(f"     -> Inner string preview: {inner_json_string[:200]}...") # Show preview
                    return False # Failed the second parse

        except json.JSONDecodeError as e:
            print(f"  -> Error: Could not parse the file content as a JSON string literal in {filepath}: {e}")
            print(f"     -> Content preview: {original_content[:200]}...") # Show preview
            # Check if it might already be valid JSON object/array instead of a string
            try:
                print("     -> Checking if content is already a valid JSON object/array...")
                data = json.loads(original_content)
                print("     -> Yes, content is already valid JSON. Proceeding to reformat.")
                # If this succeeds, 'data' is populated, and we can proceed to formatting
            except json.JSONDecodeError:
                 print("     -> No, content is not a valid JSON object/array either.")
                 return False # Failed the first parse and the fallback check

        # 4. Format the final Python object (data)
        # ensure_ascii=False is important for non-ASCII chars
        # Add a trailing newline for POSIX compatibility
        formatted_content = json.dumps(data, indent=INDENT_LEVEL, ensure_ascii=False) + '\n'

        # 5. Check if formatted content is different from the *original raw* content
        # We always want to replace if the original was a string literal, even if formatting is identical
        # Or if the original was already JSON but formatting changes it.
        # A simple content comparison is fine here. If it was a string literal, it *will* be different.
        if original_content == formatted_content:
            print(f"  -> No changes needed (already correctly formatted): {filepath}")
            return True

        # 6. Write formatted content to a temporary file
        temp_dir = os.path.dirname(filepath)
        fd, temp_path = tempfile.mkstemp(suffix=".tmpjson", prefix="fmt_", dir=temp_dir)

        try:
            # Write using UTF-8 encoding, force Unix line endings
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as tf:
                tf.write(formatted_content)

        except IOError as e:
             print(f"  -> Error: Could not write temporary file for {filepath}: {e}")
             if temp_path and os.path.exists(temp_path): os.remove(temp_path)
             return False

        # 7. Replace the original file
        try:
            shutil.move(temp_path, filepath)
            print(f"  -> Formatted and replaced: {filepath}")
            temp_path = None # Prevent deletion in finally
            return True
        except Exception as move_err:
             print(f"  -> Error: Failed to replace file {filepath} after formatting: {move_err}")
             return False # Keep temp file for inspection? Maybe not.

    except Exception as e:
        # Catch any other unexpected errors
        print(f"  -> Error: An unexpected error occurred processing {filepath}: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # 8. Clean up the temporary file if it wasn't moved
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as e:
                print(f"  -> Warning: Could not remove temporary file {temp_path}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Reads files containing JSON string literals, extracts the inner JSON, formats it, and overwrites."
    )
    parser.add_argument(
        "folder_path", help="Path to the folder containing JSON files."
    )
    args = parser.parse_args()

    folder_path = args.folder_path

    if not os.path.isdir(folder_path):
        print(f"Error: Folder '{folder_path}' does not exist.")
        exit(1)

    print(f"Starting JSON string literal processing in '{folder_path}'...")
    processed_count = 0
    success_count = 0
    error_count = 0

    for root, _, files in os.walk(folder_path):
        for filename in files:
            if filename.lower().endswith(".json"):
                filepath = os.path.join(root, filename)
                processed_count += 1
                if process_json_string_file(filepath):
                     success_count +=1
                else:
                    error_count += 1

    print("\nProcessing complete.")
    print(f"Total JSON files found: {processed_count}")
    print(f"Files successfully processed/formatted: {success_count}")
    print(f"Files with errors (parsing/IO/etc.): {error_count}")

    if error_count > 0:
        exit(1) # Indicate failure if errors occurred

if __name__ == "__main__":
    main()