from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from zotero_mcp.client import get_attachment_details, get_zotero_client

# Create an MCP server
mcp = FastMCP("Zotero")


def format_item(item: dict[str, Any]) -> str:
    """Format a Zotero item's metadata as a readable string optimized for LLM consumption"""
    data = item["data"]
    item_key = item["key"]
    item_type = data.get("itemType", "unknown")

    # Special handling for notes
    if item_type == "note":
        note_content = data.get("note", "")
        note_content = (
            note_content.replace("<p>", "").replace("</p>", "\n").replace("<br>", "\n")
        )
        note_content = note_content.replace("<strong>", "**").replace("</strong>", "**")
        note_content = note_content.replace("<em>", "*").replace("</em>", "*")

        formatted = [
            "## 📝 Note",
            f"Item Key: `{item_key}`",
        ]

        if parent_item := data.get("parentItem"):
            formatted.append(f"Parent Item: `{parent_item}`")

        if date := data.get("dateModified"):
            formatted.append(f"Last Modified: {date}")

        if tags := data.get("tags"):
            tag_list = [f"`{tag['tag']}`" for tag in tags]
            formatted.append(f"\n### Tags\n{', '.join(tag_list)}")

        formatted.append(f"\n### Note Content\n{note_content}")

        return "\n".join(formatted)

    formatted = [
        f"## {data.get('title', 'Untitled')}",
        f"Item Key: `{item_key}`",
        f"Type: {item_type}",
        f"Date: {data.get('date', 'No date')}",
    ]

    creators_by_role = {}
    for creator in data.get("creators", []):
        role = creator.get("creatorType", "contributor")
        name = ""
        if "firstName" in creator and "lastName" in creator:
            name = f"{creator['lastName']}, {creator['firstName']}"
        elif "name" in creator:
            name = creator["name"]

        if name:
            if role not in creators_by_role:
                creators_by_role[role] = []
            creators_by_role[role].append(name)

    for role, names in creators_by_role.items():
        role_display = role.capitalize() + ("s" if len(names) > 1 else "")
        formatted.append(f"{role_display}: {'; '.join(names)}")

    if publication := data.get("publicationTitle"):
        formatted.append(f"Publication: {publication}")
    if volume := data.get("volume"):
        volume_info = f"Volume: {volume}"
        if issue := data.get("issue"):
            volume_info += f", Issue: {issue}"
        if pages := data.get("pages"):
            volume_info += f", Pages: {pages}"
        formatted.append(volume_info)

    if abstract := data.get("abstractNote"):
        formatted.append(f"\n### Abstract\n{abstract}")

    if tags := data.get("tags"):
        tag_list = [f"`{tag['tag']}`" for tag in tags]
        formatted.append(f"\n### Tags\n{', '.join(tag_list)}")

    identifiers = []
    if url := data.get("url"):
        identifiers.append(f"URL: {url}")
    if doi := data.get("DOI"):
        identifiers.append(f"DOI: {doi}")
    if isbn := data.get("ISBN"):
        identifiers.append(f"ISBN: {isbn}")
    if issn := data.get("ISSN"):
        identifiers.append(f"ISSN: {issn}")

    if identifiers:
        formatted.append("\n### Identifiers\n" + "\n".join(identifiers))

    if notes := item.get("meta", {}).get("numChildren", 0):
        formatted.append(
            f"\n### Additional Information\nNumber of notes/attachments: {notes}"
        )

    return "\n".join(formatted)


@mcp.tool(
    name="zotero_item_metadata",
    description="Get metadata information about a specific Zotero item, given the item key.",
)
def get_item_metadata(item_key: str) -> str:
    """Get metadata information about a specific Zotero item"""
    zot = get_zotero_client()

    try:
        item: Any = zot.item(item_key)
        if not item:
            return f"No item found with key: {item_key}"
        return format_item(item)
    except Exception as e:
        return f"Error retrieving item metadata: {str(e)}"


@mcp.tool(
    name="zotero_item_fulltext",
    description=(
        "Get the full text content of a Zotero item. Supports pagination for large documents "
        "that exceed the 25k token limit. Use offset=0 first; the response header shows total "
        "character count and next offset. Call repeatedly with increasing offsets until "
        "remaining=0. chunk_size max is 80000 chars. "
        "item_key: parent item or attachment key."
    ),
)
def get_item_fulltext(
    item_key: str,
    offset: int = 0,
    chunk_size: int = 80000,
) -> str:
    """Get the full text content of a specific Zotero item, with optional pagination"""
    zot = get_zotero_client()
    chunk_size = min(chunk_size, 80000)

    try:
        item: Any = zot.item(item_key)
        if not item:
            return f"No item found with key: {item_key}"

        attachment = get_attachment_details(zot, item)

        header = format_item(item)

        if attachment is not None:
            attachment_info = (
                f"\n## Attachment Information\n"
                f"- **Key**: `{attachment.key}`\n"
                f"- **Type**: {attachment.content_type}"
            )

            full_text_data: Any = zot.fulltext_item(attachment.key)
            if full_text_data and "content" in full_text_data:
                text = full_text_data["content"]
                word_count = len(text.split())
                attachment_info += f"\n- **Word Count**: ~{word_count}"

                total_chars = len(text)
                chunk = text[offset:offset + chunk_size]
                remaining = max(0, total_chars - offset - len(chunk))

                if total_chars <= chunk_size and offset == 0:
                    # Small document — return everything as before
                    return f"{header}{attachment_info}\n\n## Document Content\n\n{text}"

                # Large document — return chunk with navigation header
                return (
                    f"{header}{attachment_info}\n"
                    f"- **Total chars**: {total_chars} | "
                    f"**Chunk**: [{offset}:{offset+len(chunk)}] | "
                    f"**Remaining**: {remaining} | "
                    f"**Next offset**: {offset+len(chunk)}\n\n"
                    f"## Document Content (chunk)\n\n{chunk}"
                )
            else:
                return (
                    f"{header}{attachment_info}\n\n## Document Content\n\n"
                    "[⚠️ Attachment available but text extraction not possible. "
                    "Document may be scanned or image-based.]"
                )
        else:
            return (
                f"{header}\n\n## Attachment Information\n"
                "[❌ No suitable attachment found. Item may have no attached files "
                "or they are not in a supported format.]"
            )

    except Exception as e:
        return f"Error retrieving item full text: {str(e)}"


@mcp.tool(
    name="zotero_search_items",
    description="Search for items in your Zotero library, given a query string, query mode (titleCreatorYear or everything), and optional tag search (supports boolean searches). Returned results can be looked up with zotero_item_fulltext or zotero_item_metadata.",
)
def search_items(
    query: str,
    qmode: Literal["titleCreatorYear", "everything"] | None = "titleCreatorYear",
    tag: str | None = None,
    limit: int | None = 10,
) -> str:
    """Search for items in your Zotero library"""
    zot = get_zotero_client()

    params = {"q": query, "qmode": qmode, "limit": limit}
    if tag:
        params["tag"] = tag

    zot.add_parameters(**params)
    results: Any = zot.items()

    if not results:
        return "No items found matching your query."

    header = [
        f"# Search Results for: '{query}'",
        f"Found {len(results)} items." + (f" Using tag filter: {tag}" if tag else ""),
        "Use item keys with zotero_item_metadata or zotero_item_fulltext for more details.\n",
    ]

    formatted_results = []
    for i, item in enumerate(results):
        data = item["data"]
        item_key = item.get("key", "")
        item_type = data.get("itemType", "unknown")

        if item_type == "note":
            note_content = data.get("note", "")
            note_content = (
                note_content.replace("<p>", "")
                .replace("</p>", "\n")
                .replace("<br>", "\n")
            )
            note_content = note_content.replace("<strong>", "**").replace("</strong>", "**")
            note_content = note_content.replace("<em>", "*").replace("</em>", "*")

            title_preview = ""
            if note_content:
                lines = note_content.strip().split("\n")
                first_line = lines[0].strip()
                if first_line:
                    if len(first_line) <= 50:
                        title_preview = first_line
                    else:
                        words = first_line.split()
                        title_preview = " ".join(words[:5]) + "..."

            note_title = title_preview if title_preview else "Note"
            preview = note_content.strip()
            if len(preview) > 150:
                preview = preview[:147] + "..."

            entry = [
                f"## {i + 1}. 📝 {note_title}",
                f"**Type**: Note | **Key**: `{item_key}`",
                f"\n{preview}",
            ]

            if parent_item := data.get("parentItem"):
                entry.insert(2, f"**Parent Item**: `{parent_item}`")

            if tags := data.get("tags"):
                tag_list = [f"`{tag['tag']}`" for tag in tags[:5]]
                if len(tags) > 5:
                    tag_list.append("...")
                entry.append(f"\n**Tags**: {' '.join(tag_list)}")

            formatted_results.append("\n".join(entry))
            continue

        title = data.get("title", "Untitled")
        date = data.get("date", "")

        creators = []
        for creator in data.get("creators", [])[:3]:
            if "firstName" in creator and "lastName" in creator:
                creators.append(f"{creator['lastName']}, {creator['firstName']}")
            elif "name" in creator:
                creators.append(creator["name"])

        if len(data.get("creators", [])) > 3:
            creators.append("et al.")

        creator_str = "; ".join(creators) if creators else "No authors"

        source = ""
        if pub := data.get("publicationTitle"):
            source = pub
        elif book := data.get("bookTitle"):
            source = f"In: {book}"
        elif publisher := data.get("publisher"):
            source = f"{publisher}"

        abstract = data.get("abstractNote", "")
        if len(abstract) > 150:
            abstract = abstract[:147] + "..."

        entry = [
            f"## {i + 1}. {title}",
            f"**Type**: {item_type} | **Date**: {date} | **Key**: `{item_key}`",
            f"**Authors**: {creator_str}",
        ]

        if source:
            entry.append(f"**Source**: {source}")

        if abstract:
            entry.append(f"\n{abstract}")

        if tags := data.get("tags"):
            tag_list = [f"`{tag['tag']}`" for tag in tags[:5]]
            if len(tags) > 5:
                tag_list.append("...")
            entry.append(f"\n**Tags**: {' '.join(tag_list)}")

        formatted_results.append("\n".join(entry))

    return "\n\n".join(header + formatted_results)
