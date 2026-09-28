/**
 * Which section an in-page table of contents should mark as the one being read.
 *
 * Pure over measurements the caller takes, so the rule is testable without a layout engine
 * — jsdom reports every rectangle as zero, which would make a component test agree with
 * any rule at all.
 *
 * The ordinary answer is the last section whose top has scrolled past the reading line.
 * That rule alone fails at the foot of a page: a short final section never reaches the line
 * because the page runs out of scroll first, so the highlight sits on an earlier entry while
 * the reader is looking at the last one — or at whichever one they just clicked. Once the
 * page cannot scroll further, a section the URL fragment names and that is actually on
 * screen wins (the reader chose it); failing that, the last section does.
 */
export function activeSection({
  tops,
  readingLine,
  viewportHeight,
  atBottom,
  targetIndex,
}: {
  /** Each section's top edge relative to the viewport, in document order. */
  tops: number[];
  /** How far below the viewport's top a section must reach to count as being read. */
  readingLine: number;
  viewportHeight: number;
  /** The page is scrolled as far down as it goes. */
  atBottom: boolean;
  /** The section the URL fragment names, or -1. */
  targetIndex: number;
}): number {
  if (tops.length === 0) return -1;

  if (atBottom) {
    const target = tops[targetIndex];
    const targetOnScreen =
      target !== undefined && target >= 0 && target < viewportHeight;
    return targetOnScreen ? targetIndex : tops.length - 1;
  }

  let current = 0;
  tops.forEach((top, i) => {
    if (top <= readingLine) current = i;
  });
  return current;
}
