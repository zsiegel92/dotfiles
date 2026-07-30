local function contains(values, expected)
    for _, value in ipairs(values) do
        if value == expected then
            return true
        end
    end
    return false
end

local function escape_html(value)
    return value
        :gsub("&", "&amp;")
        :gsub("<", "&lt;")
        :gsub(">", "&gt;")
end

function CodeBlock(block)
    if contains(block.classes, "mermaid") then
        return pandoc.RawBlock(
            "html",
            '<pre class="mermaid">\n' .. escape_html(block.text) .. "\n</pre>"
        )
    end
end
