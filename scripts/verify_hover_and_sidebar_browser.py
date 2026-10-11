import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path("D:/image-editor-development/mixed-input-editor/output/mixed-input-acceptance")
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as pw:
    browser = pw.chromium.launch(
        headless=True,
        executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe"
    )
    page = browser.new_page(viewport={"width": 1440, "height": 960})
    page.goto("http://127.0.0.1:8791/")
    
    # Check if login is needed
    if page.locator('input[type="password"]').count() > 0:
        page.fill('input[type="password"]', "demo123")
        page.click('button:has-text("进入工作室")')
        page.wait_for_selector(".workspaces", timeout=10000)
    
    time.sleep(1.5)
    
    # Check the filmstrip class and scroll behavior
    filmstrip = page.locator("#filmstrip")
    classes = filmstrip.get_attribute("class") or ""
    print("Filmstrip class:", classes)
    
    thumbs = page.locator("#filmstrip .thumb")
    thumb_count = thumbs.count()
    print("Thumbnail count in filmstrip:", thumb_count)
    
    # Hover over the first thumbnail
    if thumb_count > 0:
        first_thumb = thumbs.first
        first_thumb.hover()
        time.sleep(0.6)
        
        # Verify the hover preview is visible
        hover_preview = page.locator("#asset-hover-preview")
        is_visible = hover_preview.is_visible()
        card_text = page.locator(".hover-preview-badge").text_content() if is_visible else "NOT VISIBLE"
        print(f"Hover preview visible: {is_visible}, badge text: {card_text}")
        
        # Take a screenshot showing the hover preview and sidebar
        screenshot_path = OUT / "hover-preview-verification.png"
        page.screenshot(path=str(screenshot_path), full_page=False)
        print("Screenshot saved to:", screenshot_path)
    else:
        print("No thumbnails present to hover.")
        
    browser.close()
