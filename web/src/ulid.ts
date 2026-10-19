// A ULID minted on the phone: 48-bit time then 80 random bits, Crockford base 32.
const C = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

export function ulid(now = Date.now()): string {
  let time = "";
  for (let i = 0, n = now; i < 10; i++, n = Math.floor(n / 32)) time = C[n % 32] + time;
  const rand = crypto.getRandomValues(new Uint8Array(16));
  return time + Array.from(rand, (b) => C[b % 32]).join("");
}
