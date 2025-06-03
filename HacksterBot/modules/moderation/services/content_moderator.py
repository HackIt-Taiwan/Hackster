"""
Content moderation service using OpenAI's Moderation API.
"""
import os
import logging
import base64
import aiohttp
import io
import asyncio
import time
from typing import Dict, List, Union, Tuple, Optional, Any
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


def convert_to_dict(obj: Any) -> Union[Dict, Any]:
    """
    Convert an object to a dictionary for JSON serialization.
    Works recursively for nested objects with __dict__ attribute.
    
    Args:
        obj: The object to convert
        
    Returns:
        A dictionary representation or the original object if conversion not possible
    """
    if hasattr(obj, '__dict__'):
        return {key: convert_to_dict(value) for key, value in obj.__dict__.items()}
    return obj


class ContentModerator:
    """
    A class to moderate content using OpenAI's moderation API.
    
    This class provides methods to check both text and images for inappropriate content.
    """
    
    def __init__(self, openai_client: Optional[AsyncOpenAI] = None):
        """
        Initialize the content moderator with an OpenAI client.
        
        Args:
            openai_client: An optional AsyncOpenAI client. If not provided, a new one will be created.
        """
        # Initialize with provided client or create a new one using standard OpenAI API
        self.client = openai_client or AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY")
        )
        
    async def _api_call_with_retry(self, api_call, operation_name: str):
        """
        執行API調用並使用強健的重試機制
        
        重試策略：
        - 503錯誤（服務過載）：指數退避重試，最多重試12次
        - 429錯誤（請求限制）：指數退避重試，最多重試8次
        - 其他錯誤：最多重試3次
        - 最大總重試時間：8分鐘
        """
        max_retries_503 = 12  # 503錯誤最大重試次數
        max_retries_429 = 8   # 429錯誤最大重試次數
        max_retries_other = 3  # 其他錯誤最大重試次數
        max_total_time = 480   # 最大總重試時間（8分鐘）
        
        start_time = time.time()
        retry_count_503 = 0
        retry_count_429 = 0
        retry_count_other = 0
        
        while True:
            current_time = time.time()
            elapsed_time = current_time - start_time
            
            # 檢查是否超過最大重試時間
            if elapsed_time >= max_total_time:
                total_attempts = retry_count_503 + retry_count_429 + retry_count_other + 1
                logger.warning(f"[審核] {operation_name}：重試超時（{elapsed_time:.1f}秒），停止重試，總嘗試{total_attempts}次")
                raise Exception(f"{operation_name} failed after {total_attempts} attempts over {elapsed_time:.1f} seconds")
            
            try:
                total_attempts = retry_count_503 + retry_count_429 + retry_count_other + 1
                logger.info(f"[審核] {operation_name}：嘗試第{total_attempts}次")
                
                # 執行API調用
                result = await api_call()
                
                # 成功時記錄統計信息
                if total_attempts > 1:
                    logger.info(f"[審核] {operation_name}成功：總嘗試{total_attempts}次，耗時{elapsed_time:.1f}秒")
                else:
                    logger.debug(f"[審核] {operation_name}成功：首次嘗試")
                
                return result
                
            except Exception as e:
                error_message = str(e).lower()
                is_503_error = False
                is_429_error = False
                
                # 檢查錯誤類型
                if ("503" in error_message or 
                    "overloaded" in error_message or 
                    "service unavailable" in error_message or
                    "unavailable" in error_message):
                    is_503_error = True
                    retry_count_503 += 1
                    
                    if retry_count_503 > max_retries_503:
                        logger.error(f"[審核] {operation_name}：503錯誤重試次數已達上限（{max_retries_503}次）")
                        raise Exception(f"{operation_name} failed: Service overloaded after {max_retries_503} retries")
                    
                    # 503錯誤使用指數退避，但最大延遲120秒
                    delay = min(2 ** (retry_count_503 - 1), 120)
                    logger.warning(f"[審核] {operation_name}遇到503錯誤（第{retry_count_503}次），{delay}秒後重試: {e}")
                    await asyncio.sleep(delay)
                    
                elif ("429" in error_message or 
                      "rate limit" in error_message or
                      "too many requests" in error_message):
                    is_429_error = True
                    retry_count_429 += 1
                    
                    if retry_count_429 > max_retries_429:
                        logger.error(f"[審核] {operation_name}：429錯誤重試次數已達上限（{max_retries_429}次）")
                        raise Exception(f"{operation_name} failed: Rate limit exceeded after {max_retries_429} retries")
                    
                    # 429錯誤使用指數退避，但最大延遲60秒
                    delay = min(2 ** (retry_count_429 - 1), 60)
                    logger.warning(f"[審核] {operation_name}遇到429錯誤（第{retry_count_429}次），{delay}秒後重試: {e}")
                    await asyncio.sleep(delay)
                    
                else:
                    # 其他錯誤
                    retry_count_other += 1
                    
                    if retry_count_other > max_retries_other:
                        logger.error(f"[審核] {operation_name}：其他錯誤重試次數已達上限（{max_retries_other}次）")
                        raise Exception(f"{operation_name} failed: {str(e)} after {max_retries_other} retries")
                    
                    # 其他錯誤使用固定延遲
                    delay = 3
                    logger.warning(f"[審核] {operation_name}遇到其他錯誤（第{retry_count_other}次），{delay}秒後重試: {e}")
                    await asyncio.sleep(delay)
        
    async def moderate_text(self, text: str) -> Tuple[bool, Dict]:
        """
        Moderate text content using OpenAI's moderation API.
        
        Args:
            text: The text content to moderate.
            
        Returns:
            A tuple containing a boolean indicating if the content violates policies,
            and a dictionary with detailed results.
        """
        async def _api_call():
            response = await self.client.moderations.create(
                input=[{"type": "text", "text": text}],
                model="omni-moderation-latest"
            )
            
            # Get the result from the first (and only) entry
            result = response.results[0]
            
            # Check if the content is flagged
            is_flagged = result.flagged
            
            # Convert Categories and CategoryScores objects to dictionaries for JSON serialization
            categories_dict = convert_to_dict(result.categories)
            category_scores_dict = convert_to_dict(result.category_scores)
            
            # Return flagged status and detailed results
            return is_flagged, {
                "categories": categories_dict,
                "category_scores": category_scores_dict,
                "flagged": result.flagged
            }
        
        try:
            return await self._api_call_with_retry(_api_call, "文字內容審核")
        except Exception as e:
            logger.error(f"Error moderating text after all retries: {str(e)}")
            # In case of error, return False to prevent false positives
            return False, {"error": str(e)}
    
    async def moderate_image(self, image_url: str) -> Tuple[bool, Dict]:
        """
        Moderate image content using OpenAI's moderation API.
        
        Args:
            image_url: The URL of the image to moderate.
            
        Returns:
            A tuple containing a boolean indicating if the image violates policies,
            and a dictionary with detailed results.
        """
        async def _api_call():
            response = await self.client.moderations.create(
                input=[{"type": "image_url", "image_url": {"url": image_url}}],
                model="omni-moderation-latest"
            )
            
            # Get the result from the first (and only) entry
            result = response.results[0]
            
            # Check if the content is flagged
            is_flagged = result.flagged
            
            # Convert Categories and CategoryScores objects to dictionaries for JSON serialization
            categories_dict = convert_to_dict(result.categories)
            category_scores_dict = convert_to_dict(result.category_scores)
            
            # Return flagged status and detailed results
            return is_flagged, {
                "categories": categories_dict,
                "category_scores": category_scores_dict,
                "flagged": result.flagged
            }
        
        try:
            return await self._api_call_with_retry(_api_call, "圖片內容審核")
        except Exception as e:
            logger.error(f"Error moderating image after all retries: {str(e)}")
            # In case of error, return False to prevent false positives
            return False, {"error": str(e)}
    
    async def moderate_image_from_file(self, image_data: bytes, image_type: str) -> Tuple[bool, Dict]:
        """
        Moderate image content from binary data using OpenAI's moderation API.
        
        Args:
            image_data: The binary image data to moderate.
            image_type: The MIME type of the image (e.g., 'image/png').
            
        Returns:
            A tuple containing a boolean indicating if the image violates policies,
            and a dictionary with detailed results.
        """
        async def _api_call():
            # Convert image data to base64
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            # Create data URL format for the image
            data_url = f"data:{image_type};base64,{base64_image}"
            
            response = await self.client.moderations.create(
                input=[{"type": "image_url", "image_url": {"url": data_url}}],
                model="omni-moderation-latest"
            )
            
            # Get the result from the first (and only) entry
            result = response.results[0]
            
            # Check if the content is flagged
            is_flagged = result.flagged
            
            # Convert Categories and CategoryScores objects to dictionaries for JSON serialization
            categories_dict = convert_to_dict(result.categories)
            category_scores_dict = convert_to_dict(result.category_scores)
            
            # Return flagged status and detailed results
            return is_flagged, {
                "categories": categories_dict,
                "category_scores": category_scores_dict,
                "flagged": result.flagged
            }
        
        try:
            return await self._api_call_with_retry(_api_call, "檔案圖片內容審核")
        except Exception as e:
            logger.error(f"Error moderating image from file after all retries: {str(e)}")
            # In case of error, return False to prevent false positives
            return False, {"error": str(e)}
    
    async def download_image(self, image_url: str) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Download an image from a URL.
        
        Args:
            image_url: The URL of the image to download.
            
        Returns:
            A tuple containing the binary image data and its content type, or None if an error occurred.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as response:
                    if response.status == 200:
                        content_type = response.headers.get('Content-Type', 'image/jpeg')
                        image_data = await response.read()
                        return image_data, content_type
                    else:
                        logger.error(f"Failed to download image. Status: {response.status}")
                        return None, None
        except Exception as e:
            logger.error(f"Error downloading image: {str(e)}")
            return None, None
    
    async def moderate_content(self, text: str = None, image_urls: List[str] = None) -> Tuple[bool, Dict]:
        """
        Moderate both text and images in a single call.
        
        Args:
            text: Optional text content to moderate.
            image_urls: Optional list of image URLs to moderate.
            
        Returns:
            A tuple containing a boolean indicating if any content violates policies,
            and a dictionary with detailed results.
        """
        results = {
            "text_result": None,
            "image_results": [],
            "flagged": False
        }
        
        # Moderate text if provided
        if text:
            text_flagged, text_result = await self.moderate_text(text)
            results["text_result"] = text_result
            if text_flagged:
                results["flagged"] = True
        
        # Moderate images if provided
        if image_urls:
            for url in image_urls:
                image_flagged, image_result = await self.moderate_image(url)
                results["image_results"].append({
                    "url": url,
                    "result": image_result
                })
                if image_flagged:
                    results["flagged"] = True
        
        return results["flagged"], results 