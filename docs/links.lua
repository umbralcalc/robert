-- Pandoc filter for the GitHub Pages site. Each page is a markdown file from the
-- repo; its relative links are written for GitHub, so this rewrites them:
--   - a link to another page on the site goes to that page's .html;
--   - any other repo path goes to the file on GitHub;
--   - the README's raw.githubusercontent logo is served from the site itself.
-- Mermaid blocks become <pre class="mermaid"> for mermaid.js to render.
--
-- The page's own directory in the repo arrives as the `source-dir` metadata.

local REPO = "https://github.com/umbralcalc/robert/blob/main/"
local RAW = "https://raw.githubusercontent.com/umbralcalc/robert/main/"

-- Repo path of each source file that is also a page on the site.
local PAGES = {
  ["README.md"] = "index.html",
  ["cloud/README.md"] = "cloud.html",
  ["CHANGELOG.md"] = "changelog.html",
}

local source_dir = ""

-- Resolve `target` against the page's directory, folding `.` and `..`.
local function repo_path(target)
  local parts = {}
  local joined = source_dir ~= "" and (source_dir .. "/" .. target) or target
  for part in joined:gmatch("[^/]+") do
    if part == ".." then
      table.remove(parts)
    elseif part ~= "." then
      table.insert(parts, part)
    end
  end
  return table.concat(parts, "/")
end

local function rewrite(target)
  if target:match("^%a[%w+.-]*:") or target:match("^#") or target:match("^/") then
    return target
  end
  local path, anchor = target:match("^([^#]*)(#?.*)$")
  local resolved = repo_path(path)
  if PAGES[resolved] then
    return PAGES[resolved] .. anchor
  end
  return REPO .. resolved .. anchor
end

return {
  {
    Meta = function(meta)
      if meta["source-dir"] then
        source_dir = pandoc.utils.stringify(meta["source-dir"])
      end
    end,
  },
  {
    Link = function(el)
      el.target = rewrite(el.target)
      return el
    end,
    Image = function(el)
      if el.src:sub(1, #RAW) == RAW then
        el.src = el.src:sub(#RAW + 1)
      end
      return el
    end,
    RawInline = function(el)
      if el.format == "html" then
        el.text = el.text:gsub(RAW:gsub("%p", "%%%0"), "")
      end
      return el
    end,
    RawBlock = function(el)
      if el.format == "html" then
        el.text = el.text:gsub(RAW:gsub("%p", "%%%0"), "")
      end
      return el
    end,
    CodeBlock = function(el)
      if el.classes:includes("mermaid") then
        local escaped = el.text:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;")
        return pandoc.RawBlock("html", '<pre class="mermaid">' .. escaped .. "</pre>")
      end
    end,
  },
}
