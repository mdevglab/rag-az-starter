#!/bin/bash


# 1. Make it executable: chmod +x clean_json.sh
# 2. Run it with the folder path as argument: ./clean_json.sh /path/to/your/folder

# Check if folder path is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <folder_path>"
    exit 1
fi

folder_path="$1"

# Check if the folder exists
if [ ! -d "$folder_path" ]; then
    echo "Error: Folder '$folder_path' does not exist."
    exit 1
fi

# Find all JSON files recursively and process them
find "$folder_path" -type f -name "*.json" | while read -r file; do
    echo "Processing: $file"
    
    # Create a temporary file
    temp_file=$(mktemp)
    
    # Remove CR (carriage return) characters and save to temp file
    tr -d '\r' < "$file" > "$temp_file"
    
    # Check if the file was modified
    if ! cmp -s "$file" "$temp_file"; then
        # Replace original file with the cleaned version
        mv "$temp_file" "$file"
        echo "Cleaned Windows line endings from: $file"
    else
        # No changes needed, remove temp file
        rm "$temp_file"
        echo "No changes needed for: $file"
    fi
done

echo "Processing complete."





# #!/bin/bash

# # Check if input file exists
# if [ -z "$1" ] || [ ! -f "$1" ]; then
#     echo "Usage: $0 <input.json> [output.json]"
#     exit 1
# fi

# input_file="$1"
# output_file="${2:-$input_file}"  # Default: overwrite input file

# # Step 1: Remove \r (Windows line endings)
# cleaned=$(tr -d '\r' < "$input_file")

# # Step 2: Reformat JSON using Bash string manipulation
# # (Basic formatting - indents with 2 spaces)
# formatted=$(
#     echo "$cleaned" | 
#     sed 's/[{[]/\n&\n/g' |       # Add newlines before/after { [ 
#     sed 's/[]}]/\n&\n/g' |       # Add newlines before/after } ]
#     sed 's/[,:]/\0\n/g' |        # Add newline after , and :
#     sed '/^$/d' |                # Remove empty lines
#     awk '{
#         if ($0 ~ /[}\]]/) { indent--; }  # Decrease indent after } or ]
#         printf "%*s%s\n", indent*2, "", $0;
#         if ($0 ~ /[{\[]/) { indent++; }  # Increase indent after { or [
#     }'
# )

# # Save to output file
# echo "$formatted" > "$output_file"
# echo "✅ Successfully cleaned and formatted: $output_file"