#!/bin/bash

# Usage: ./concat_files.sh <directory> <output_file> [find_options]
# Example: ./concat_files.sh ./output ./result.txt -name "*.txt"

# Ensure directory and output file are provided
if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <directory> <output_file> [find_options]"
    exit 1
fi

# Assign arguments
DIRECTORY=$1
OUTPUT_FILE=$2
shift 2
FIND_OPTIONS=$@

# Check if directory exists
if [[ ! -d "$DIRECTORY" ]]; then
    echo "Error: Directory '$DIRECTORY' does not exist."
    exit 1
fi

# Create or empty the output file
> "$OUTPUT_FILE"

# Find and process files
find "$DIRECTORY" $FIND_OPTIONS \
  -type d \( -name .git -o -name .venv \) -prune -false -o \
  -type f | while read -r FILE; do
    # Check if the file is a valid UTF-8 text file
    if file --mime-encoding "$FILE" | grep -q 'utf-8'; then
        echo "Processing $FILE"
        echo "==== File: $FILE ====" >> "$OUTPUT_FILE"
        echo >> "$OUTPUT_FILE"
        cat "$FILE" >> "$OUTPUT_FILE"
        echo >> "$OUTPUT_FILE"
    else
        echo "Skipping non-UTF-8 file: $FILE"
    fi
done

echo "All files concatenated into $OUTPUT_FILE"

