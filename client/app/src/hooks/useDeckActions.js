// Thin consumer hook over DeckContext. Exists for parity with the target
// structure; call sites can prefer `useDeck()` directly if they need the
// raw context value.

import { useDeck } from "../context/DeckContext.jsx";

export function useDeckActions() {
  return useDeck();
}
