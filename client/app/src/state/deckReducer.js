// Deck state shape:
//   {
//     slides: [{ id, position, title, html, created_at, updated_at }, ...],
//     selectedIndex: number,   // -1 when empty
//   }
//
// Actions:
//   SLIDES_LOADED { slides }      — initial REST fetch result
//   SLIDE_CREATED { slide }       — SSE from CreateSlideTool
//   SLIDE_UPDATED { slide }       — SSE from UpdateSlideTool
//   SLIDE_DELETED { slide_id }    — SSE from DeleteSlideTool
//   SLIDES_REPLACED { slides }    — SSE from ReorderSlideTool (full list)
//   SELECT { index }              — user clicks a thumbnail
//   RESET                         — clears deck (on project switch)
//
// Slides are always kept sorted by `position`.

export const INITIAL_DECK_STATE = { slides: [], selectedIndex: -1 };

const sortByPosition = (list) =>
  [...list].sort((a, b) => (a.position ?? 0) - (b.position ?? 0));

const clampIndex = (index, length) => {
  if (length === 0) return -1;
  if (index < 0) return 0;
  if (index >= length) return length - 1;
  return index;
};

export function deckReducer(state, action) {
  switch (action.type) {
    case "SLIDES_LOADED": {
      const slides = sortByPosition(action.slides || []);
      return {
        slides,
        selectedIndex: slides.length > 0 ? 0 : -1,
      };
    }

    case "SLIDE_CREATED": {
      const slide = action.slide;
      if (!slide?.id) return state;
      // Replace if already present (backend may re-emit on retry), else insert.
      const withoutDup = state.slides.filter((s) => s.id !== slide.id);
      const slides = sortByPosition([...withoutDup, slide]);
      const idx = slides.findIndex((s) => s.id === slide.id);
      return { slides, selectedIndex: idx >= 0 ? idx : state.selectedIndex };
    }

    case "SLIDE_UPDATED": {
      const slide = action.slide;
      if (!slide?.id) return state;
      const idx = state.slides.findIndex((s) => s.id === slide.id);
      if (idx < 0) return state;
      const slides = sortByPosition(
        state.slides.map((s) => (s.id === slide.id ? slide : s)),
      );
      return { ...state, slides };
    }

    case "SLIDE_DELETED": {
      const id = action.slide_id;
      if (!id) return state;
      const slides = state.slides.filter((s) => s.id !== id);
      return {
        slides,
        selectedIndex: clampIndex(state.selectedIndex, slides.length),
      };
    }

    case "SLIDES_REPLACED": {
      const slides = sortByPosition(action.slides || []);
      // Preserve selection by id if the selected slide still exists.
      const prevId = state.slides[state.selectedIndex]?.id;
      const newIdx = prevId
        ? slides.findIndex((s) => s.id === prevId)
        : -1;
      return {
        slides,
        selectedIndex: newIdx >= 0 ? newIdx : clampIndex(state.selectedIndex, slides.length),
      };
    }

    case "SELECT":
      return { ...state, selectedIndex: clampIndex(action.index ?? 0, state.slides.length) };

    case "RESET":
      return INITIAL_DECK_STATE;

    default:
      return state;
  }
}
