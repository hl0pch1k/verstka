// Формула плана (LaTeX агента: «$\int_a^b f(x)\,dx = F(b) - F(a)$ — пояснение») как строка текста для плашки
// вкладки «План» (D-plan `dpl-fx`): знаки — символами Юникода, индексы и степени — надстрочными и подстрочными
// цифрами и буквами, где они есть, дроби — через «/», пределы — «lim n→∞». KaTeX не нужен: плашка показывает формулу
// текстом, как на доске.

const SYM: Record<string, string> = {
  infty: "∞", to: "→", rightarrow: "→", leftarrow: "←", Rightarrow: "⇒", Leftrightarrow: "⇔", approx: "≈", neq: "≠", ne: "≠",
  leq: "≤", le: "≤", geq: "≥", ge: "≥", cdot: "·", times: "×", pm: "±", mp: "∓", partial: "∂", nabla: "∇", in: "∈", notin: "∉",
  subset: "⊂", cup: "∪", cap: "∩", forall: "∀", exists: "∃", mid: "|", circ: "∘", cdots: "…", ldots: "…", dots: "…", prime: "′",
  equiv: "≡", sim: "∼", propto: "∝", degree: "°", "%": "%", "{": "{", "}": "}", "|": "‖",
  alpha: "α", beta: "β", gamma: "γ", Gamma: "Γ", delta: "δ", Delta: "Δ", epsilon: "ε", varepsilon: "ε", zeta: "ζ", eta: "η", theta: "θ",
  vartheta: "θ", Theta: "Θ", kappa: "κ", lambda: "λ", Lambda: "Λ", mu: "μ", nu: "ν", xi: "ξ", Xi: "Ξ", pi: "π", Pi: "Π", rho: "ρ",
  sigma: "σ", Sigma: "Σ", tau: "τ", phi: "φ", varphi: "φ", Phi: "Φ", chi: "χ", psi: "ψ", Psi: "Ψ", omega: "ω", Omega: "Ω",
};
/** Буквоподобные знаки: пробел после команды перед буквой — только разделитель («\Delta x» → «Δx»). */
const LETTERLIKE = new Set(["infty", "partial", "nabla", "alpha", "beta", "gamma", "Gamma", "delta", "Delta", "epsilon", "varepsilon", "zeta", "eta", "theta", "vartheta", "Theta",
  "kappa", "lambda", "Lambda", "mu", "nu", "xi", "Xi", "pi", "Pi", "rho", "sigma", "Sigma", "tau", "phi", "varphi", "Phi", "chi", "psi", "Psi", "omega", "Omega"]);
const BIG: Record<string, string> = { int: "∫", iint: "∬", iiint: "∭", oint: "∮", sum: "Σ", prod: "Π" };
const TEXT = new Set(["text", "mathrm", "mathbf", "mathit", "operatorname", "textbf", "textit", "mathcal", "mathbb", "boldsymbol"]);
const SPACE: Record<string, string> = { ",": " ", ";": " ", ":": " ", " ": " ", quad: " ", qquad: " ", "!": "" };

const SUP: Record<string, string> = {
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻", "−": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
  a: "ᵃ", b: "ᵇ", c: "ᶜ", d: "ᵈ", e: "ᵉ", f: "ᶠ", g: "ᵍ", h: "ʰ", i: "ⁱ", j: "ʲ", k: "ᵏ", l: "ˡ", m: "ᵐ", n: "ⁿ", o: "ᵒ", p: "ᵖ", r: "ʳ", s: "ˢ", t: "ᵗ",
  u: "ᵘ", v: "ᵛ", w: "ʷ", x: "ˣ", y: "ʸ", z: "ᶻ", "′": "′",
};
const SUB: Record<string, string> = {
  "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉", "+": "₊", "-": "₋", "−": "₋", "=": "₌", "(": "₍", ")": "₎",
  a: "ₐ", e: "ₑ", h: "ₕ", i: "ᵢ", j: "ⱼ", k: "ₖ", l: "ₗ", m: "ₘ", n: "ₙ", o: "ₒ", p: "ₚ", r: "ᵣ", s: "ₛ", t: "ₜ", u: "ᵤ", v: "ᵥ", x: "ₓ",
};

/** Группа после позиции `i`: {…} целиком, команда «\name» или один знак; пробелы перед ней пропускаются. */
function group(s: string, i: number): [string, number] {
  while (s[i] === " ") i++;
  if (s[i] === "{") {
    let depth = 0;
    for (let j = i; j < s.length; j++) {
      if (s[j] === "\\") { j++; continue; }
      if (s[j] === "{") depth++;
      else if (s[j] === "}" && --depth === 0) return [s.slice(i + 1, j), j + 1];
    }
    return [s.slice(i + 1), s.length];
  }
  if (s[i] === "\\") {
    const m = /^\\([A-Za-z]+|.)/.exec(s.slice(i));
    return m ? [m[0], i + m[0].length] : ["", i + 1];
  }
  return [s[i] ?? "", i + 1];
}

/** Одна «часть» дроби или корня: число, буква с индексами, вызов «ρ(r)» — без скобок; иначе в скобках. */
const atom = (t: string) => /^\d+$/.test(t) || /^\p{L}[²³¹⁰-₟ᴬ-ᵪⱼ]*$/u.test(t) || /^\p{L}\([^()]*\)$/u.test(t);
const wrap = (t: string, loose = false) => (loose ? (/[\s+\-−=·×]/.test(t) ? `(${t})` : t) : atom(t) ? t : `(${t})`);

function script(t: string, sup: boolean): string {
  const map = sup ? SUP : SUB;
  const chars = [...t.replace(/\s+/g, "")];
  if (chars.length && chars.every((c) => map[c])) return chars.map((c) => map[c]).join("");
  const body = t.trim();
  return `${sup ? "^" : "_"}${[...body].length > 1 ? `(${body})` : body}`;
}

function conv(s: string): string {
  let out = "";
  let i = 0;
  while (i < s.length) {
    const ch = s[i];
    if (ch === "\\") {
      const m = /^\\([A-Za-z]+|.)/.exec(s.slice(i));
      const name = m ? m[1] : "";
      i += m ? m[0].length : 1;
      if (name === "frac" || name === "dfrac" || name === "tfrac") {
        const [a, i1] = group(s, i);
        const [b, i2] = group(s, i1);
        i = i2;
        out += `${wrap(conv(a), true)}/${wrap(conv(b))}`;
      } else if (name === "sqrt") {
        let deg = "";
        if (s[i] === "[") {
          const end = s.indexOf("]", i);
          deg = script(conv(s.slice(i + 1, end < 0 ? s.length : end)), true);
          i = end < 0 ? s.length : end + 1;
        }
        const [a, i1] = group(s, i);
        i = i1;
        out += `${deg}√${wrap(conv(a))}`;
      } else if (TEXT.has(name)) {
        const [a, i1] = group(s, i);
        i = i1;
        out += conv(a);
      } else if (name === "left" || name === "right") {
        while (s[i] === " ") i++;
        if (s[i] === "\\") {
          const [d, i1] = group(s, i);
          i = i1;
          out += conv(d);
        } else {
          out += s[i] === "." ? "" : s[i] ?? "";
          i++;
        }
      } else if (name === "lim") {
        let j = i;
        while (s[j] === " ") j++;
        out += "lim";
        if (s[j] === "_") {
          const [a, i1] = group(s, j + 1);
          i = i1;
          out += ` ${conv(a).replace(/\s+/g, "")}`;
        }
        out += " ";
      } else if (BIG[name]) {
        out += BIG[name];
        // пределы знака — сразу за ним, в любом порядке; дальше — пробел
        for (let k = 0; k < 2; k++) {
          let j = i;
          while (s[j] === " ") j++;
          if (s[j] !== "_" && s[j] !== "^") break;
          const [a, i1] = group(s, j + 1);
          out += script(conv(a), s[j] === "^");
          i = i1;
        }
        out += " ";
        while (s[i] === " ") i++;
      } else if (name in SPACE) {
        out += SPACE[name];
      } else if (SYM[name]) {
        out += SYM[name];
        if (LETTERLIKE.has(name)) {
          let j = i;
          while (s[j] === " ") j++;
          if (/\p{L}/u.test(s[j] ?? "")) i = j;
        }
      } else out += name;
    } else if (ch === "^" || ch === "_") {
      const [a, i1] = group(s, i + 1);
      i = i1;
      out += script(conv(a), ch === "^");
    } else if (ch === "{") {
      const [a, i1] = group(s, i);
      i = i1;
      out += conv(a);
    } else if (ch === "}") {
      i++;
    } else {
      out += ch === "'" ? "′" : ch;
      i++;
    }
  }
  return out;
}

export function latexText(tex: string): string {
  return conv(tex)
    .replace(/\s+/g, " ")
    .replace(/ - /g, " − ")
    .replace(/([(=]\s?)-(?=\S)/g, "$1−")
    .replace(/^-/, "−")
    .trim();
}

/** Формулы слайда: каждая «$…$» — отдельной плашкой; без долларов — строка до пояснения после « — ». */
export function formulaParts(formula: string | null | undefined): string[] {
  const f = (formula ?? "").trim();
  if (!f) return [];
  const parts = [...f.matchAll(/\$([^$]+)\$/g)].map((m) => latexText(m[1])).filter(Boolean);
  if (parts.length) return parts;
  const head = f.split(/\s+—\s+/)[0];
  return head ? [latexText(head)] : [];
}
