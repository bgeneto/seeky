const CHUNK_CHARS: usize = 1_200;
const OVERLAP_CHARS: usize = 200;

pub fn chunk_text(text: &str) -> Vec<(String, usize, usize)> {
    let chars: Vec<char> = text.chars().collect();
    if chars.is_empty() {
        return Vec::new();
    }
    let mut chunks = Vec::new();
    let mut start = 0usize;
    while start < chars.len() {
        let mut end = (start + CHUNK_CHARS).min(chars.len());
        if end < chars.len() {
            // Prefer a paragraph/sentence/whitespace boundary near the end.
            let window_start = end.saturating_sub(180);
            if let Some(position) = (window_start..end)
                .rev()
                .find(|index| matches!(chars[*index], '\n' | '.' | '!' | '?' | ';' | ' '))
            {
                end = position + 1;
            }
        }
        let chunk: String = chars[start..end].iter().collect();
        let trimmed = chunk.trim();
        if trimmed.chars().count() >= 40 {
            let leading = chunk
                .chars()
                .take_while(|character| character.is_whitespace())
                .count();
            let trailing = chunk
                .chars()
                .rev()
                .take_while(|character| character.is_whitespace())
                .count();
            chunks.push((trimmed.to_string(), start + leading, end - trailing));
        }
        if end >= chars.len() {
            break;
        }
        start = end.saturating_sub(OVERLAP_CHARS);
    }
    chunks
}
