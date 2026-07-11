"""挑战检测和处理工具"""
from typing import Tuple

from DrissionPage._pages.chromium_tab import ChromiumTab
from loguru import logger
from pyquery import PyQuery as pq  # type: ignore[import-untyped]

from src.config.settings import CHALLENGE_BOX_SELECTORS, CHALLENGE_SELECTORS, CHALLENGE_TITLES


def under_challenge(html_text: str) -> bool:
    """
    检查页面是否处于挑战状态
    
    Args:
        html_text: 要检查的HTML内容
        
    Returns:
        bool: 如果页面处于挑战状态则为True，否则为False
    """
    # 获取页面标题
    if not html_text:
        return False
        
    page_title = str(pq(html_text)('title').text()).lower()  # type: ignore
    logger.debug(f"under_challenge page_title={page_title}")
    
    for title in CHALLENGE_TITLES:
        if page_title == title.lower():
            return True
            
    for selector in CHALLENGE_SELECTORS:
        html_doc = pq(html_text)
        if html_doc(selector):
            return True
            
    return False


def under_box_challenge(html_text: str) -> bool:
    """
    检查页面是否处于盒子挑战状态
    
    Args:
        html_text: 要检查的HTML内容
        
    Returns:
        bool: 如果页面处于盒子挑战状态则为True，否则为False
    """
    if not html_text:
        return False
        
    for selector in CHALLENGE_BOX_SELECTORS:
        html_doc = pq(html_text)
        if html_doc(selector):
            return True
            
    return False


def sync_cf_retry(page: ChromiumTab, tries: int = 5) -> Tuple[bool, bool]:
    """
    同步重试CloudFlare挑战解决
    
    Args:
        page: 浏览器页面/标签页
        tries: 重试尝试次数
        
    Returns:
        Tuple[bool, bool]: (成功, 是否挑战)
    """
    success = False
    cf = True
    user_tries = tries
    
    while tries > 0:
        # 非CF网站
        if not under_challenge(page.html):
            success = True
            break
            
        try:
            page.wait(5)
            if not under_challenge(page.html):
                success = True
                break
                
            cf_solution = page.ele('tag:input@name=cf-turnstile-response', timeout=3)  # type: ignore[union-attr]
            cf_wrapper = cf_solution.parent()  # type: ignore[union-attr]
            cf_iframe = cf_wrapper.shadow_root.ele("tag:iframe", timeout=3)  # type: ignore[union-attr]

            box = cf_iframe.ele('tag:body').shadow_root  # type: ignore[union-attr]
            cf_button = box.ele("tag:input")  # type: ignore[union-attr]
            cf_button.click()  # type: ignore[union-attr]
            
        except Exception as e:
            page.wait(1)
            logger.debug(f"DrissionPage 错误: {e}")
            success = False
            
        tries -= 1
        
    if tries == user_tries:
        cf = False
        
    return success, cf


def sync_cf_box_retry(page: ChromiumTab, tries: int = 3) -> Tuple[bool, bool]:
    """
    同步重试CloudFlare盒子挑战解决
    
    Args:
        page: Browser page/tab
        tries: Number of retry attempts
        
    Returns:
        Tuple[bool, bool]: (success, was_challenge)
    """
    success = False
    cf = True
    user_tries = tries
    
    while tries > 0:
        # 首先等待页面加载完成
        page.wait(5)
        
        # 检查是否处于挑战状态
        if not under_box_challenge(page.html):
            # 等待额外时间确保页面完全加载
            page.wait(2)
            # 再次检查挑战状态
            if not under_box_challenge(page.html):
                success = True
                cf = False
                break
            else:
                logger.debug("Challenge detected after additional wait")
        
        try:
            # 等待cf-turnstile-response元素可用，增加超时时间
            cf_solution = page.ele('tag:input@name=cf-turnstile-response', timeout=10)  # type: ignore[union-attr]
            if not cf_solution:
                logger.debug("cf-turnstile-response element not found, waiting longer...")
                page.wait(3)
                cf_solution = page.ele('tag:input@name=cf-turnstile-response', timeout=10)  # type: ignore[union-attr]
                if not cf_solution:
                    logger.debug("cf-turnstile-response element still not found after additional wait")
                    # 如果找不到元素，等待更长时间再重试
                    page.wait(5)
                    continue
            
            cf_wrapper = cf_solution.parent()  # type: ignore[union-attr]
            cf_iframe = cf_wrapper.shadow_root.ele("tag:iframe", timeout=10)  # type: ignore[union-attr]

            box = cf_iframe.ele('tag:body').shadow_root  # type: ignore[union-attr]
            
            # 等待挑战按钮可用
            cf_button = None
            for _ in range(5):  # 最多重试5次等待按钮
                try:
                    cf_button = box.ele("tag:input", timeout=3)  # type: ignore[union-attr]
                    if cf_button:
                        break
                    page.wait(1)
                except Exception:
                    page.wait(1)
            
            if cf_button:
                cf_button.click()  # type: ignore[union-attr]
                logger.debug("CloudFlare challenge button clicked")
            else:
                logger.debug("CloudFlare challenge button not found")
                
            # 等待挑战完成
            for _ in range(10):  # 最多等待10秒
                try:
                    visibility = box.ele('tag:div@id=success').style('visibility')  # type: ignore[union-attr]
                    if visibility == 'visible':
                        success = True
                        logger.debug("CloudFlare challenge completed successfully")
                        break
                    page.wait(1)
                except Exception:
                    page.wait(1)
                    
        except Exception as e:
            page.wait(1)
            logger.debug(f"DrissionPage Error: {e}")
            success = False
            
        tries -= 1
        
    if tries == user_tries:
        cf = False
        
    return success, cf
