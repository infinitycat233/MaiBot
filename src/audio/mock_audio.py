import asyncio
from src.common.logger import get_logger

logger = get_logger("MockAudio")


class MockAudioPlayer:
    """
    一个模拟的音频播放器，它会根据音频数据的"长度"来模拟播放时间。
    """

    def __init__(self, audio_data: bytes):
        self._audio_data = audio_data
        # 模拟音频时长：假设每 1024 字节代表 0.5 秒的音频
        self._duration = (len(audio_data) / 1024.0) * 0.5

    async def play(self):
        """模拟播放音频。该过程可以被中断。"""
        if self._duration <= 0:
            return
        logger.info(f"开始播放模拟音频，预计时长: {self._duration:.2f} 秒...")
        try:
            await asyncio.sleep(self._duration)
            logger.info("模拟音频播放完毕。")
        except asyncio.CancelledError:
            logger.info("音频播放被中断。")
            raise  # 重新抛出异常，以便上层逻辑可以捕获它


class MockAudioGenerator:
    """
    一个模拟的文本到语音（TTS）生成器。
    """

    def __init__(self):
        # 模拟生成速度：每秒生成的字符数
        self.chars_per_second = 25.0

    async def generate(self, text: str) -> bytes:
        """
        模拟从文本生成音频数据。该过程可以被中断。

        Args:
            text: 需要转换为音频的文本。

        Returns:
            模拟的音频数据（bytes）。
        """
        if not text:
            return b""

        generation_time = len(text) / self.chars_per_second
        logger.info(f"模拟生成音频... 文本长度: {len(text)}, 预计耗时: {generation_time:.2f} 秒...")
        try:
            await asyncio.sleep(generation_time)
            # 生成虚拟的音频数据，其长度与文本长度成正比
            mock_audio_data = b"\x01\x02\x03" * (len(text) * 40)
            logger.info(f"模拟音频生成完毕，数据大小: {len(mock_audio_data) / 1024:.2f} KB。")
            return mock_audio_data
        except asyncio.CancelledError:
            logger.info("音频生成被中断。")
            raise  # 重新抛出异常
