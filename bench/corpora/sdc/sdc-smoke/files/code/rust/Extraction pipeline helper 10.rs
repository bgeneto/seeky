pub fn extraction_pipeline_helper_10_010_checksum(data: &[u8]) -> u64 {
    let mut value: u64 = 0;
    for byte in data {
        value = value.wrapping_mul(131).wrapping_add(u64::from(*byte));
    }
    value
}

pub fn extraction_pipeline_helper_10_010_normalize(input: &str) -> String {
    input
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
}
