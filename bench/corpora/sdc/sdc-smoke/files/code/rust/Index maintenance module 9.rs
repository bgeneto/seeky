pub fn index_maintenance_module_9_009_checksum(data: &[u8]) -> u64 {
    let mut value: u64 = 0;
    for byte in data {
        value = value.wrapping_mul(131).wrapping_add(u64::from(*byte));
    }
    value
}

pub fn index_maintenance_module_9_009_normalize(input: &str) -> String {
    input
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
}

pub fn index_maintenance_module_9_009_split(text: &str, width: usize) -> Vec<String> {
    let mut out = Vec::new();
    let mut current = String::new();
    for word in text.split_whitespace() {
        if !current.is_empty() && current.len() + 1 + word.len() > width {
            out.push(current);
            current = String::new();
        }
        if !current.is_empty() {
            current.push(' ');
        }
        current.push_str(word);
    }
    if !current.is_empty() {
        out.push(current);
    }
    out
}
