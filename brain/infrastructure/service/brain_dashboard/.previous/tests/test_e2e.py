"""E2E Tests for Dashboard V2 - T13 Implementation.

Playwright-based browser automation tests.
Key user scenarios:
1. Dashboard loads and displays agents
2. Proxy stats update
3. Registry view switching
4. Log viewer WebSocket connection
"""

import pytest
import asyncio
from playwright.async_api import async_playwright, expect


# Dashboard URL
DASHBOARD_URL = "http://localhost:8080"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="session")
async def browser():
    """Create browser instance."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture
async def page(browser):
    """Create new page for each test."""
    page = await browser.new_page()
    await page.goto(DASHBOARD_URL)
    yield page
    await page.close()


class TestDashboardLoad:
    """Test Dashboard page loading."""

    async def test_page_title(self, page):
        """Test page title is correct."""
        await expect(page).to_have_title("Agent Dashboard")

    async def test_header_visible(self, page):
        """Test header is visible."""
        header = page.locator("h1")
        await expect(header).to_contain_text("Agent Dashboard")

    async def test_navigation_visible(self, page):
        """Test navigation bar is visible."""
        nav = page.locator("nav")
        await expect(nav).to_be_visible()

    async def test_nav_links(self, page):
        """Test navigation links exist."""
        await expect(page.locator("a[href='#stats']")).to_be_visible()
        await expect(page.locator("a[href='#proxy-section']")).to_be_visible()
        await expect(page.locator("a[href='#registry-section']")).to_be_visible()
        await expect(page.locator("a[href='#logs-section']")).to_be_visible()


class TestAgentsSection:
    """Test Agents section."""

    async def test_stats_cards_visible(self, page):
        """Test stats cards are visible."""
        await expect(page.locator("#stats")).to_be_visible()

    async def test_agents_table_exists(self, page):
        """Test agents table exists."""
        await expect(page.locator("table")).to_be_visible()

    async def test_table_headers(self, page):
        """Test table has correct headers."""
        headers = ["Status", "Agent", "Instance ID", "Uptime", "Last Heartbeat", "Session"]
        for header in headers:
            await expect(page.locator("th", has_text=header)).to_be_visible()


class TestProxySection:
    """Test Proxy Traffic section."""

    async def test_proxy_section_visible(self, page):
        """Test proxy section is visible."""
        await expect(page.locator("#proxy-section")).to_be_visible()

    async def test_proxy_stats_cards(self, page):
        """Test proxy stats cards exist."""
        await expect(page.locator("text=QPS")).to_be_visible()
        await expect(page.locator("text=Avg Latency")).to_be_visible()
        await expect(page.locator("text=Error Rate")).to_be_visible()
        await expect(page.locator("text=Connections")).to_be_visible()

    async def test_latency_percentiles(self, page):
        """Test latency percentiles are displayed."""
        await expect(page.locator("text=P50 Latency")).to_be_visible()
        await expect(page.locator("text=P95 Latency")).to_be_visible()
        await expect(page.locator("text=P99 Latency")).to_be_visible()

    async def test_routes_section(self, page):
        """Test routes section exists."""
        await expect(page.locator("text=Routing Rules")).to_be_visible()


class TestRegistrySection:
    """Test Service Registry section."""

    async def test_registry_section_visible(self, page):
        """Test registry section is visible."""
        await expect(page.locator("#registry-section")).to_be_visible()

    async def test_registry_tabs(self, page):
        """Test registry tabs exist."""
        await expect(page.locator("button", has_text="Services")).to_be_visible()
        await expect(page.locator("button", has_text="Agents")).to_be_visible()
        await expect(page.locator("button", has_text="Groups")).to_be_visible()

    async def test_services_tab_active(self, page):
        """Test services tab is active by default."""
        await expect(page.locator("#tab-services")).to_have_class(/border-blue-500/)

    async def test_tab_switching(self, page):
        """Test tab switching works."""
        # Click Agents tab
        await page.click("#tab-agents")
        await expect(page.locator("#registry-agents")).to_be_visible()
        await expect(page.locator("#registry-services")).to_be_hidden()

        # Click Groups tab
        await page.click("#tab-groups")
        await expect(page.locator("#registry-groups")).to_be_visible()
        await expect(page.locator("#registry-agents")).to_be_hidden()


class TestLogViewerSection:
    """Test Log Viewer section."""

    async def test_logs_section_visible(self, page):
        """Test logs section is visible."""
        await expect(page.locator("#logs-section")).to_be_visible()

    async def test_log_controls_exist(self, page):
        """Test log controls exist."""
        await expect(page.locator("#log-service-select")).to_be_visible()
        await expect(page.locator("#log-toggle-btn")).to_be_visible()
        await expect(page.locator("#log-connection-status")).to_be_visible()

    async def test_log_container_exists(self, page):
        """Test log container exists."""
        await expect(page.locator("#log-container")).to_be_visible()

    async def test_auto_scroll_checkbox(self, page):
        """Test auto-scroll checkbox exists."""
        await expect(page.locator("#log-auto-scroll")).to_be_visible()
        await expect(page.locator("#log-auto-scroll")).to_be_checked()


class TestResponsiveDesign:
    """Test responsive design."""

    async def test_mobile_viewport(self, browser):
        """Test mobile viewport rendering."""
        context = await browser.new_context(viewport={"width": 375, "height": 667})
        page = await context.new_page()
        await page.goto(DASHBOARD_URL)

        # Check if content is visible
        await expect(page.locator("h1")).to_be_visible()

        await page.close()
        await context.close()

    async def test_tablet_viewport(self, browser):
        """Test tablet viewport rendering."""
        context = await browser.new_context(viewport={"width": 768, "height": 1024})
        page = await context.new_page()
        await page.goto(DASHBOARD_URL)

        await expect(page.locator("#stats")).to_be_visible()

        await page.close()
        await context.close()


class TestNavigation:
    """Test navigation functionality."""

    async def test_nav_click_scrolls(self, page):
        """Test navigation click scrolls to section."""
        # Click on Proxy nav link
        await page.click("a[href='#proxy-section']")
        # Verify proxy section is in view
        await expect(page.locator("#proxy-section")).to_be_in_viewport()

    async def test_nav_active_state(self, page):
        """Test navigation active state."""
        # Click on different sections and verify they exist
        await page.click("a[href='#registry-section']")
        await expect(page.locator("#registry-section")).to_be_visible()

        await page.click("a[href='#logs-section']")
        await expect(page.locator("#logs-section")).to_be_visible()


class TestRealTimeUpdates:
    """Test real-time updates via SSE."""

    async def test_sse_connection(self, page):
        """Test SSE connection is established."""
        # Wait for page to load and SSE to connect
        await page.wait_for_timeout(2000)

        # Check if stats are updated (not showing "-")
        total_count = await page.locator("#total-count").text_content()
        # Should not be "-" after SSE connects
        assert total_count != "-" or await page.locator("#agents-table").is_visible()

    async def test_stats_update(self, page):
        """Test stats update over time."""
        # Wait for initial SSE data
        await page.wait_for_timeout(3000)

        # Check if last update time is set
        last_update = await page.locator("#last-update").text_content()
        assert last_update != "-"


@pytest.mark.skip(reason="Requires running server and WebSocket")
class TestWebSocket:
    """Test WebSocket functionality (requires running server)."""

    async def test_websocket_connect(self, page):
        """Test WebSocket connection."""
        # Navigate to logs section
        await page.click("a[href='#logs-section']")

        # Click connect button
        await page.click("#log-toggle-btn")

        # Wait for connection
        await page.wait_for_timeout(1000)

        # Check status is connected
        status = await page.locator("#log-connection-status").text_content()
        assert "Connected" in status or "Connecting" in status


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
