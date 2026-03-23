use rand::Rng;

const ALPHABET: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789";

pub fn generate_session_id(length: usize) -> String {
    let mut rng = rand::thread_rng();
    (0..length)
        .map(|_| {
            let idx = rng.gen_range(0..ALPHABET.len());
            ALPHABET[idx] as char
        })
        .collect()
}

pub fn generate_verification_code() -> String {
    let mut rng = rand::thread_rng();
    let code: u32 = rng.gen_range(100000..1000000);
    code.to_string()
}

pub fn generate_auth_token(length: usize) -> String {
    let mut rng = rand::thread_rng();
    (0..length)
        .map(|_| {
            let idx = rng.gen_range(0..ALPHABET.len());
            ALPHABET[idx] as char
        })
        .collect()
}
