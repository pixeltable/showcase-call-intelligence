import { EXAMPLE_DATA } from "../api/client";

export function ExampleNotice() {
  if (!EXAMPLE_DATA) return null;
  return <aside aria-label="Example data provenance" className="border-b border-slate-700 bg-slate-900 px-4 py-3 text-sm sm:px-6">
    <div className="mx-auto max-w-7xl">
      <p className="font-medium text-amber-200">Example data · no live computation</p>
      <p className="mt-1 max-w-prose text-slate-300">Recorded WhisperX transcript with an authored illustrative summary.
        Search matches keywords. Comments stay in this browser.</p>
      <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1">
        <a className="text-indigo-300 underline underline-offset-4" href="/examples/provenance.json" target="_blank" rel="noreferrer">Inspect provenance</a>
        <a className="text-indigo-300 underline underline-offset-4" href="https://github.com/pixeltable/showcase-call-intelligence/blob/main/docs/WALKTHROUGH.md">Run the backend and extend a rule</a>
      </div>
    </div>
  </aside>;
}
