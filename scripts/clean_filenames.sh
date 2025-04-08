#!/bin/bash


# 1. chmod +x clean_filenames.sh
# 2. ./clean_filenames.sh "/path/to/your/folder"

# Check if folder path is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <folder_path> [--recursive]"
    exit 1
fi

folder_path="$1"
recursive=false

# Check if recursive mode is enabled
if [ "$2" = "--recursive" ]; then
    recursive=true
fi

# Function to clean a single filename
clean_filename() {
    local filename="$1"
    local dirname="$(dirname "$filename")"
    local basename="$(basename "$filename")"

    # Remove spaces and special chars, keep only [a-zA-Z0-9_.-]
    new_basename=$(echo "$basename" | sed -E -e 's/[^a-zA-Z0-9_.-]/_/g' -e 's/_+/_/g' -e 's/^_//' -e 's/_$//')

    if [ "$basename" != "$new_basename" ]; then
        local new_filename="$dirname/$new_basename"
        # Avoid overwriting existing files
        if [ -e "$new_filename" ]; then
            echo "Warning: '$new_filename' already exists. Skipping rename of '$filename'."
        else
            mv -- "$filename" "$new_filename"
            echo "Renamed: '$basename' → '$new_basename'"
        fi
    fi
}

# Process files
if [ "$recursive" = true ]; then
    # Recursive mode (find all files)
    find "$folder_path" -type f | while read -r file; do
        clean_filename "$file"
    done
else
    # Non-recursive (only files in the given folder)
    find "$folder_path" -maxdepth 1 -type f | while read -r file; do
        clean_filename "$file"
    done
fi

echo "Filename cleaning complete."