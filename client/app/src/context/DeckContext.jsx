import { createContext, useContext, useEffect, useReducer, useCallback, useRef, useState } from "react";
import { deckReducer, INITIAL_DECK_STATE } from "../state/deckReducer.js";
import {
  listSlides,
  reorderSlide as reorderSlideApi,
  deleteSlide as deleteSlideApi,
  isForbidden,
} from "../api.js";

const DeckContext = createContext(null);

// DeckProvider owns:
// - the slide list (reducer state, keyed on project),
// - the initial REST fetch when projectId changes,
// - a dispatcher that `useChat`'s SSE handler calls on `slide_*` events.
//
// Consumers read `{slides, selectedIndex, setSelectedIndex}`. The SSE
// hookup uses the callback returned by `useDeckEventSink()` — this
// indirection keeps `useChat` decoupled from the reducer shape.

export function DeckProvider({ projectId, getToken, children }) {
  const [state, dispatch] = useReducer(deckReducer, INITIAL_DECK_STATE);
  // Tracks the initial REST fetch on project switch. Distinct from
  // optimistic mutation paths (reorder/delete) — those don't toggle
  // this flag because the optimistic dispatch already updated the UI.
  // Consumers (filmstrip) use this to render skeleton thumbnails on
  // first paint, so the empty list isn't ambiguous between "still
  // loading" and "no slides yet".
  const [isLoading, setIsLoading] = useState(false);
  // 403 sentinel. Set when ``listSlides`` (or a later mutation) returns
  // 403 — typically because the user lost access to this project mid-
  // session (removed via the share dialog from another tab, or admin
  // disabled the membership). ChatPage observes this flag and renders
  // a "no access" banner with a "Back to projects" exit.
  const [forbidden, setForbidden] = useState(false);

  const activeProjectRef = useRef(projectId);
  activeProjectRef.current = projectId;

  useEffect(() => {
    let cancelled = false;
    if (!projectId) {
      dispatch({ type: "RESET" });
      setIsLoading(false);
      setForbidden(false);
      return () => { cancelled = true; };
    }
    setIsLoading(true);
    setForbidden(false);
    (async () => {
      try {
        const token = getToken ? await getToken() : null;
        const slides = await listSlides(token, projectId);
        if (cancelled) return;
        if (activeProjectRef.current !== projectId) return;
        dispatch({ type: "SLIDES_LOADED", slides });
      } catch (err) {
        if (cancelled) return;
        if (activeProjectRef.current !== projectId) return;
        if (isForbidden(err)) {
          dispatch({ type: "RESET" });
          setForbidden(true);
        } else {
          dispatch({ type: "RESET" });
        }
      } finally {
        if (!cancelled && activeProjectRef.current === projectId) {
          setIsLoading(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [projectId, getToken]);

  const setSelectedIndex = useCallback(
    (index) => dispatch({ type: "SELECT", index }),
    [],
  );

  // Track the latest slide list in a ref so the reorder callback can compute
  // an optimistic ordering and revert on error without re-creating itself
  // every time `state.slides` changes (which would re-bind drag handlers in
  // the filmstrip on every dispatch).
  const slidesRef = useRef(state.slides);
  slidesRef.current = state.slides;

  // User-driven reorder from the slides panel. Optimistically reorders
  // locally, then calls the API. On success, re-applies the canonical list
  // returned by the server (positions are recomputed there). On failure,
  // reverts to the previous order.
  const reorderSlide = useCallback(
    async (fromIndex, toIndex) => {
      const current = slidesRef.current;
      if (
        fromIndex === toIndex
        || fromIndex < 0
        || fromIndex >= current.length
        || toIndex < 0
        || toIndex > current.length - 1
      ) {
        return;
      }
      const moving = current[fromIndex];
      if (!moving) return;

      const reordered = current.slice();
      reordered.splice(fromIndex, 1);
      reordered.splice(toIndex, 0, moving);
      const afterSlideId = toIndex === 0 ? null : reordered[toIndex - 1].id;

      // Remap `position` to match the new array order. The reducer re-sorts
      // by `position`, so without this the optimistic dispatch sorts right
      // back to the original order and the move only becomes visible after
      // the server response lands. Server is authoritative — its response
      // will overwrite these with canonical positions, but the visible
      // order will already match so there's no flicker.
      const optimistic = reordered.map((s, i) => ({ ...s, position: i }));

      const previous = current;
      dispatch({ type: "SLIDES_REPLACED", slides: optimistic });

      try {
        const token = getToken ? await getToken() : null;
        const serverSlides = await reorderSlideApi(token, moving.id, { afterSlideId });
        if (activeProjectRef.current !== projectId) return;
        dispatch({ type: "SLIDES_REPLACED", slides: serverSlides });
      } catch (err) {
        if (activeProjectRef.current !== projectId) return;
        dispatch({ type: "SLIDES_REPLACED", slides: previous });
        if (isForbidden(err)) setForbidden(true);
      }
    },
    [getToken, projectId],
  );

  // User-driven delete from the slides panel. Optimistically removes the
  // slide; on API failure, restores it via SLIDE_CREATED (which sorts back
  // into its original `position`).
  const deleteSlide = useCallback(
    async (slideId) => {
      if (!slideId) return;
      const slide = slidesRef.current.find((s) => s.id === slideId);
      if (!slide) return;

      dispatch({ type: "SLIDE_DELETED", slide_id: slideId });

      try {
        const token = getToken ? await getToken() : null;
        await deleteSlideApi(token, slideId);
      } catch (err) {
        if (activeProjectRef.current !== projectId) return;
        dispatch({ type: "SLIDE_CREATED", slide });
        if (isForbidden(err)) setForbidden(true);
      }
    },
    [getToken, projectId],
  );

  // Apply a raw SSE slide event. Called from useChat's stream handler.
  const applySlideEvent = useCallback((type, data) => {
    switch (type) {
      case "slide_created":
        dispatch({ type: "SLIDE_CREATED", slide: data?.slide });
        break;
      case "slide_updated":
        dispatch({ type: "SLIDE_UPDATED", slide: data?.slide });
        break;
      case "slide_deleted":
        dispatch({ type: "SLIDE_DELETED", slide_id: data?.slide_id });
        break;
      case "slides_replaced":
        dispatch({ type: "SLIDES_REPLACED", slides: data?.slides });
        break;
      default:
        break;
    }
  }, []);

  const value = {
    projectId,
    getToken,
    slides: state.slides,
    selectedIndex: state.selectedIndex,
    selectedSlide: state.selectedIndex >= 0 ? state.slides[state.selectedIndex] : null,
    isLoading,
    forbidden,
    setSelectedIndex,
    reorderSlide,
    deleteSlide,
    applySlideEvent,
  };

  return <DeckContext.Provider value={value}>{children}</DeckContext.Provider>;
}

export function useDeck() {
  const ctx = useContext(DeckContext);
  if (!ctx) throw new Error("useDeck must be used within <DeckProvider>");
  return ctx;
}
