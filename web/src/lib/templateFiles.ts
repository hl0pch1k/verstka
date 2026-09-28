// Which files the template upload takes — the mirror of the server's list (verstka/ingest/convert.py ACCEPTED_EXTS):
// PowerPoint (.pptx, .potx, .pptm, .ppsx, .thmx, legacy .ppt/.pot/.pps) and OpenDocument (.odp, .otp). The server
// converts everything to .pptx and checks the bytes; here only the name is looked at, to say early what is wrong.

export const TEMPLATE_EXTS = [".pptx", ".potx", ".pptm", ".potm", ".ppsx", ".ppsm", ".thmx", ".ppt", ".pot", ".pps", ".odp", ".otp"];

/** The file picker's `accept`: the extensions and the PowerPoint / OpenDocument media types. */
export const TEMPLATE_ACCEPT = [
  ...TEMPLATE_EXTS,
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.presentationml.template",
  "application/vnd.ms-powerpoint",
  "application/vnd.oasis.opendocument.presentation",
].join(",");

const EXT_RE = /\.[a-z0-9]+$/i;

export function isTemplateFile(name: string): boolean {
  const ext = (name.match(EXT_RE)?.[0] ?? "").toLowerCase();
  return TEMPLATE_EXTS.includes(ext);
}

/** What to say about a file the upload does not take (null when it takes it). */
export function templateFileProblem(name: string): string | null {
  if (isTemplateFile(name)) return null;
  const ext = (name.match(EXT_RE)?.[0] ?? "").toLowerCase();
  if (ext === ".key") return "Это файл Keynote. Экспортируйте его в PowerPoint (Файл → Экспортировать в → PowerPoint) и загрузите .pptx";
  if (ext === ".pdf") return "PDF не подойдёт — нужен файл PowerPoint: .pptx или .potx";
  if (ext === ".gslides" || ext === ".url" || ext === ".webloc") return "Скачайте презентацию из Google Slides: Файл → Скачать → Microsoft PowerPoint (.pptx)";
  return "Нужен шаблон презентации: .pptx, .potx, .ppt или .odp";
}

/** The template's name without its extension («Годовой отчёт.potx» → «Годовой отчёт»). */
export function templateStem(name: string): string {
  return name.replace(EXT_RE, "") || name;
}
