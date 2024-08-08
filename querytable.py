import pysam
import os
import random

# Open the BAM file
bamfile = pysam.AlignmentFile("/Users/AlvinZhang2026/hg002_revio_grch38_minimap2_juncbed.chr20.part.bam", "rb")

# Parses the CIGAR strings from the BAM file, returning sequences, CIGAR strings, and clip types (soft or hard).
def parseCigar(givenBamfile):
    seq = []  # List to store sequences and their query names
    cigar = []  # List to store CIGAR strings
    SoH = []  # Soft or hard clip indicator

    for read in givenBamfile.fetch():
        if read.is_secondary:
            continue
        seq.append((read.query_name, read.query_sequence))  # Store query name and sequence
        cigar.append(read.cigarstring)  # Store CIGAR string

        if read.cigartuples:
            for (op, le) in read.cigartuples:
                if op == 4 and not SoH:  # Check for soft clip
                    SoH.append(1)  # Soft clip indicator
                elif op == 5 and not SoH:  # Check for hard clip
                    SoH.append(2)  # Hard clip indicator

    return [seq, cigar, SoH]  # Return sequences, CIGAR strings, and clip information

# Creates arrays of query and reference positions, including splice information, allowing differentiation between all operations.
def QRtable2(givenBamfile, SoH):
    query_positions2 = []  # List to store query positions
    reference_positions2 = []  # List to store reference positions
    splices = []  # Positions of splices (query index)
    splices2 = []  # Detailed splice information (query and reference positions)

    for read in givenBamfile.fetch():
        queryindex = read.query_alignment_start if SoH == 1 else 0  # Adjust query index based on clip type
        referenceindex = read.reference_start  # Initialize reference index

        for op, le in read.cigartuples:
            if op == 0:  # Match
                for i in range(le):
                    query_positions2.append(queryindex)  # Store query position
                    reference_positions2.append(referenceindex)  # Store reference position
                    queryindex += 1  # Increment query index
                    referenceindex += 1  # Increment reference index
            elif op == 1:  # Insertion
                queryindex += le  # Skip inserted bases
            elif op == 2:  # Deletion
                referenceindex += le  # Skip deleted bases
            elif op == 3:  # Skip (splice)
                splices.append([queryindex - 1, queryindex])  # Store splice positions
                splices2.append([[queryindex - 1, referenceindex], [queryindex, referenceindex + le]])
                query_positions2.append(queryindex)
                reference_positions2.append(referenceindex)
                referenceindex += le  # Increment reference index by splice length

    return [query_positions2, reference_positions2, splices, splices2]  # Return positions and splice info

# Extracts subreads from the query sequences, returning a list with detailed subread information.
def extract_subreads(query_seq, start_positions, length, long_read_id, reference_positions):
    subreads = []  # List to store subreads
    used_positions = set()  # Track positions that have been used

    for i, start_pos in enumerate(start_positions):
        if start_pos is not None and start_pos not in used_positions and (start_pos + length <= len(query_seq)):
            subread = query_seq[start_pos:start_pos + length]  # Extract subread
            ref_start = reference_positions[i] if i < len(reference_positions) else None  # Reference start position
            ref_end = reference_positions[i + length - 1] if i + length - 1 < len(reference_positions) else None  # Reference end position
            subread_id = f"{long_read_id}_subread_{i + 1}_start_{ref_start}_end_{ref_end}"  # Generate subread ID
            subreads.append((subread, ref_start, ref_end, long_read_id, subread_id))  # Store subread information
            used_positions.update(range(start_pos, start_pos + length))  # Mark positions as used

    return subreads  # Return list of subreads

# Converts subreads to a FASTA file format for further RNA sequencing analysis.
def subreads_to_fasta(subreads, output_file):
    with open(output_file, 'w') as fasta_file:
        for subread, ref_start, ref_end, long_read_id, subread_id in subreads:
            fasta_file.write(f">{subread_id}\n")  # Write header with subread ID
            fasta_file.write(f"{subread}\n")  # Write subread sequence

# Generates random subreads for a given query sequence
def generate_random_subreads(query_seq, reference_positions, subread_length):
    num_subreads = len(query_seq) // subread_length  # Determine number of subreads based on sequence length
    random_subreads = []  # List to store random subreads
    for _ in range(num_subreads):
        if len(query_seq) <= subread_length:
            break
        start = random.randint(0, len(query_seq) - subread_length)  # Randomly select start position
        subread = query_seq[start:start + subread_length]  # Extract subread
        ref_start = reference_positions[start] if start < len(reference_positions) else None  # Reference start position
        ref_end = reference_positions[start + subread_length - 1] if start + subread_length - 1 < len(reference_positions) else None  # Reference end position
        random_subreads.append((subread, start, start + subread_length - 1, ref_start, ref_end))  # Store subread information
    return random_subreads  # Return list of random subreads

# Tests all the functions, printing their results.
def testFunctions(givenBamfile):
    parseCigarArray = parseCigar(givenBamfile)  # Parse CIGAR strings
    seqs = parseCigarArray[0]  # Extract sequences
    SoHArray = parseCigarArray[2]  # Extract soft/hard clip information
    SoH = SoHArray[0] if SoHArray else 0  # Determine soft/hard clip type
    QRtable2Array = QRtable2(givenBamfile, SoH)  # Generate query and reference position tables
    reference_positions = QRtable2Array[1]  # Extract reference positions

    # Collect all subreads and random subreads for all long reads
    all_subreads = []  # List to store all subreads
    random_subreads_list = []  # List to store random subreads
    long_read_ids = []  # List to store long read sequence IDs

    for read_id, read_seq in seqs:
        long_read_ids.append(read_id)  # Add the long read sequence ID to the list
        print(f"Processing long read ID: {read_id}")
        length_of_subread = 150  # Define length of subreads

        # Generate random subreads for the current long read
        random_subreads = generate_random_subreads(read_seq, reference_positions, length_of_subread)

        for i, (subread, start, end, ref_start, ref_end) in enumerate(random_subreads):
            subread_id = f"{read_id}_random_subread_{i + 1}_start_{ref_start}_end_{ref_end}"  # Generate subread ID
            random_subreads_list.append((subread, start, end, ref_start, ref_end, subread_id))  # Store subread information
            print(f"Random Subread ID: {subread_id}, Subread: {subread}, Start: {start}, End: {end}")

        all_subreads.extend(random_subreads)  # Collect random subreads from all reads

    # Print all long read sequence IDs
    print("Long Read Sequence IDs:")
    for long_read_id in long_read_ids:
        print(long_read_id)

    # Output random subreads to FASTA
    output_file3 = "/Users/AlvinZhang2026/bio_data/random_subreads.fasta"
    subreads_to_fasta([(subread, ref_start, ref_end, read_id, subread_id) for subread, start, end, ref_start, ref_end, subread_id in random_subreads_list], output_file3)

# Run the test function
testFunctions(bamfile)
