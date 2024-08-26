import pysam
import re
from tabulate import tabulate

def read_and_process_reads(long_read_bam, subread_bam):
    long_read_cigar_dict = {}
    subread_cigar_list = []

    print("Opening BAM files...")
    long_read_file = pysam.AlignmentFile(long_read_bam, "rb")
    subread_file = pysam.AlignmentFile(subread_bam, "rb")

    print("Processing long reads...")
    for read in long_read_file.fetch():
        if read.cigarstring:
            base_seq_id = read.query_name.replace('/', '=')
            long_read_cigar_dict[base_seq_id] = (read.cigarstring, read.query_sequence)
        else:
            print(f"Warning: Read {read.query_name} has no CIGAR string")

    print(f"Long reads dictionary: {len(long_read_cigar_dict)} entries")

    print("Processing subreads...")
    for read in subread_file.fetch():
        full_seq_id = read.query_name
        base_seq_id = full_seq_id.split('random_subread')[0].rstrip('_')
        base_seq_id = base_seq_id.replace('=', '/')
        cigar = read.cigarstring

        start_stop_match = re.search(r'_start_(\d+)_end_(\d+)$', full_seq_id)
        if start_stop_match:
            start, stop = map(int, start_stop_match.groups())
        else:
            start, stop = 0, 0

        if cigar:
            subread_cigar_list.append((base_seq_id, cigar, start, stop, full_seq_id))
        else:
            print(f"Warning: Subread {full_seq_id} has no CIGAR string")

    print(f"Subread list: {len(subread_cigar_list)} entries")

    return long_read_cigar_dict, subread_cigar_list

def parse_cigar(cigar_string):
    return [(int(length), op) for length, op in re.findall(r'(\d+)([MIDNSHP=X])', cigar_string)]

def get_cigar_name(op):
    return {
        'M': 'match',
        'I': 'insertion',
        'D': 'deletion',
        'N': 'splice',
        'S': 'soft_clip',
        'H': 'hard_clip',
        'P': 'padding',
        '=': 'match',
        'X': 'mismatch'
    }.get(op, 'unknown')

def generate_expected_cigar_string(long_cigar, start, stop):
    expected_cigar = []
    current_position = 0
    total_matches = 0

    for length, op in long_cigar:
        if current_position >= stop:
            break
        if current_position + length <= start:
            current_position += length
            continue

        overlap_start = max(start, current_position)
        overlap_end = min(stop, current_position + length)
        overlap_length = overlap_end - overlap_start

        if overlap_length > 0:
            if op == 'M':
                expected_cigar.append((overlap_length, op))
                total_matches += overlap_length
            else:
                expected_cigar.append((overlap_length, op))

        current_position += length

    if total_matches < 150:
        remaining_matches = 150 - total_matches
        for i, (length, op) in enumerate(expected_cigar):
            if op == 'M':
                if length >= remaining_matches:
                    expected_cigar[i] = (length + remaining_matches, 'M')
                    remaining_matches = 0
                    break
                else:
                    remaining_matches -= length

        if remaining_matches > 0:
            expected_cigar.append((remaining_matches, 'M'))

    expected_cigar_string = ''.join([f"{length}{op}" for length, op in expected_cigar])
    return expected_cigar_string

def calculate_accuracy_precision(summary, shared_summary):
    accurate_bases = sum(shared_summary[op] for op in ['match', 'insertion', 'deletion', 'splice'])
    total_detected_bases = sum(summary[op] for op in ['match', 'insertion', 'deletion', 'splice'])

    accuracy = accurate_bases / total_detected_bases if total_detected_bases > 0 else 0
    precision = accurate_bases / (accurate_bases + summary['unmatched_sub']) if (accurate_bases + summary['unmatched_sub']) > 0 else 0

    return accuracy, precision

def align_subread_to_longread(long_read_cigar, long_read_sequence, subread_cigar, start, stop):
    long_cigar = parse_cigar(long_read_cigar)
    sub_cigar = parse_cigar(subread_cigar)

    expected_cigar_string = generate_expected_cigar_string(long_cigar, start, stop)

    summary = {
        'match': 0,
        'insertion': 0,
        'deletion': 0,
        'splice': 0,
        'soft_clip': 0,
        'unmatched_sub': 0
    }

    shared_summary = {
        'match': 0,
        'insertion': 0,
        'deletion': 0,
        'splice': 0,
        'soft_clip': 0
    }

    expected_cigar_parsed = parse_cigar(expected_cigar_string)
    sub_cigar_parsed = parse_cigar(subread_cigar)

    expected_index = 0
    sub_index = 0

    while expected_index < len(expected_cigar_parsed) and sub_index < len(sub_cigar_parsed):
        expected_len, expected_op = expected_cigar_parsed[expected_index]
        sub_len, sub_op = sub_cigar_parsed[sub_index]

        if expected_op == sub_op:
            common_len = min(expected_len, sub_len)
            if get_cigar_name(expected_op) in shared_summary:
                shared_summary[get_cigar_name(expected_op)] += common_len

            expected_len -= common_len
            sub_len -= common_len

            if expected_len == 0:
                expected_index += 1
            else:
                expected_cigar_parsed[expected_index] = (expected_len, expected_op)

            if sub_len == 0:
                sub_index += 1
            else:
                sub_cigar_parsed[sub_index] = (sub_len, sub_op)
        else:
            sub_index += 1

    for op in shared_summary:
        summary[op] += shared_summary[op]

    total_expected_bases = sum(length for length, op in expected_cigar_parsed if op in ['M', 'I', 'D', 'N'])
    total_subread_bases = sum(length for length, op in sub_cigar_parsed if op in ['M', 'I', 'D', 'N'])
    summary['unmatched_sub'] = total_subread_bases - sum(shared_summary[op] for op in shared_summary)

    accuracy, precision = calculate_accuracy_precision(summary, shared_summary)

    return summary, accuracy, precision, expected_cigar_string

def compare_cigar_strings(long_read_cigar_dict, subread_cigar_list, output_file):
    results = []
    matched_count = 0
    unmatched_count = 0
    fully_matched_count = 0
    total_subreads = len(subread_cigar_list)

    total_summary = {
        'match': 0,
        'insertion': 0,
        'deletion': 0,
        'splice': 0,
        'soft_clip': 0,
        'unmatched_sub': 0
    }

    total_accuracy = 0
    total_precision = 0

    for base_seq_id, subread_cigar, start, stop, full_seq_id in subread_cigar_list:
        converted_id = base_seq_id.split('/')[0] + "/" + "/".join(base_seq_id.split('/')[1:])
        if converted_id.replace('/', '=') in long_read_cigar_dict:
            matched_count += 1
            long_read_cigar, long_read_sequence = long_read_cigar_dict[converted_id.replace('/', '=')]
            summary, accuracy, precision, expected_cigar_string = align_subread_to_longread(
                long_read_cigar, long_read_sequence, subread_cigar, start, stop
            )

            fully_matched = (accuracy == 1.0 and precision == 1.0)
            if fully_matched:
                fully_matched_count += 1

            total_accuracy += accuracy
            total_precision += precision

            for key in total_summary:
                total_summary[key] += summary.get(key, 0)

            results.append([
                full_seq_id, subread_cigar, expected_cigar_string, start, stop, long_read_cigar,
                summary['match'], summary['insertion'], summary['deletion'], summary['splice'],
                summary['soft_clip'], summary['unmatched_sub'], accuracy, precision
            ])
        else:
            unmatched_count += 1

    if total_subreads > 0:
        average_accuracy = total_accuracy / total_subreads
        average_precision = total_precision / total_subreads
    else:
        average_accuracy = 0
        average_precision = 0

    with open(output_file, 'w') as f:
        header = [
            "Subread ID", "Subread CIGAR", "Expected CIGAR", "Start", "Stop", "Long Read CIGAR",
            "Shared Matches", "Shared Insertions", "Shared Deletions", "Shared Splices",
            "Soft Clips", "Unmatched Subread", "Accuracy", "Precision"
        ]
        f.write('\t'.join(header) + '\n')
        for result in results:
            f.write('\t'.join(map(str, result)) + '\n')

    print(f"Matched {matched_count}/{total_subreads} subreads to long reads.")
    print(f"Fully matched: {fully_matched_count}/{total_subreads} subreads.")
    print(f"Average Accuracy: {average_accuracy:.4f}")
    print(f"Average Precision: {average_precision:.4f}")
    print(f"Results saved to {output_file}")

# Example usage:
long_read_bam_path = '/Users/AlvinZhang2026/hg002_revio_grch38_minimap2_juncbed.chr20.part.bam'
subread_bam_path = '/Users/AlvinZhang2026/STARsortedoutput16.bam'
output_file_path = '/Users/AlvinZhang2026/comparison_results.tsv'

long_read_cigar_dict, subread_cigar_list = read_and_process_reads(long_read_bam_path, subread_bam_path)
compare_cigar_strings(long_read_cigar_dict, subread_cigar_list, output_file_path)

