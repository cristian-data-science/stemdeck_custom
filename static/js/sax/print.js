// «🎷 Saxo»: the saxophone's part on paper. The server engraves the line as
// the page plays it (app/api/sax.py sax_part: written for the saxophone, in
// the song's bars); Verovio, the score page's engraver, lays it out in A4
// pages, and the browser prints them (or saves them as a PDF). Loaded only
// when asked for: Verovio is large.

let toolkit = null;

async function verovio() {
  if (!toolkit) {
    const [{ default: createVerovioModule }, { VerovioToolkit }] = await Promise.all([
      import("/vendor/verovio/verovio-module.mjs"),
      import("/vendor/verovio/verovio.mjs"),
    ]);
    toolkit = new VerovioToolkit(await createVerovioModule());
  }
  return toolkit;
}

/** The part's MEI as A4 pages of SVG (Verovio's units: tenths of a mm). */
export async function partPages(mei) {
  const tk = await verovio();
  tk.setOptions({
    pageWidth: 2100,
    pageHeight: 2970,
    pageMarginTop: 120,
    pageMarginBottom: 120,
    pageMarginLeft: 140,
    pageMarginRight: 140,
    scale: 45,
    adjustPageHeight: false,
    breaks: "auto",
    header: "auto",
    footer: "none",
    svgViewBox: true,
  });
  tk.loadData(mei);
  const pages = [];
  for (let p = 1; p <= tk.getPageCount(); p++) pages.push(tk.renderToSVG(p));
  return pages;
}

/** Into the page's print area, then the browser's print dialog. */
export async function printPart(mei, host) {
  const pages = await partPages(mei);
  host.innerHTML = pages.map((svg) => `<div class="sx-print-page">${svg}</div>`).join("");
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  window.print();
  return pages.length;
}
