"""
EAN-13 智能条码生成服务 (严格遵循 ean13_generator.html 规范)
规则：
1. 3 位前缀/国家代码 (如 450-499 范围或随机指定)
2. 4 位厂商代码 (相邻非同号、非连号)
3. 5 位产品代码 (相邻非同号、非连号)
4. 1 位标准 EAN-13 校验码 (奇偶加权 Modulo-10 校验算法)
"""
import random
from typing import Set, List, Optional


class EANService:
    """提供 EAN-13 校验码计算、非连号/非同号生成与批量排重生成服务"""

    @staticmethod
    def generate_non_adjacent_digits(length: int) -> str:
        """生成指定长度的数字串 (相邻非同号、非连号)"""
        if length <= 0:
            return ""
        digits = []
        for i in range(length):
            if i == 0:
                candidates = list(range(10))
            else:
                prev = digits[i - 1]
                excluded = {prev, prev - 1, prev + 1}
                candidates = [d for d in range(10) if d not in excluded]
            picked = random.choice(candidates)
            digits.append(picked)
        return "".join(map(str, digits))

    @staticmethod
    def calculate_checksum(s12: str) -> int:
        """
        计算 EAN-13 标准校验码 (第 13 位)
        奇数位之和 + 偶数位之和 * 3，取 10 的补数
        """
        if len(s12) < 12:
            s12 = s12.zfill(12)[-12:]
        digits = [int(ch) for ch in s12[:12]]
        odd_sum = sum(digits[i] for i in range(0, 12, 2))      # 1, 3, 5, 7, 9, 11 位
        even_sum = sum(digits[i] for i in range(1, 12, 2))     # 2, 4, 6, 8, 10, 12 位
        total = (even_sum * 3) + odd_sum
        check_digit = (10 - (total % 10)) % 10
        return check_digit

    @staticmethod
    def validate_ean13(ean: str) -> bool:
        """校验一个 13 位条码是否符合 EAN-13 校验码规则"""
        if not ean or len(ean) != 13 or not ean.isdigit():
            return False
        expected_check = EANService.calculate_checksum(ean[:12])
        return int(ean[12]) == expected_check

    @staticmethod
    def generate_single_ean(country_code: Optional[str] = None, mfg_code: Optional[str] = None) -> str:
        """生成单个合规的 13 位 EAN 条码"""
        country = country_code or str(random.randint(450, 499))
        country = country.zfill(3)[-3:]
        mfg = mfg_code or EANService.generate_non_adjacent_digits(4)
        mfg = mfg.zfill(4)[-4:]
        prod = EANService.generate_non_adjacent_digits(5)

        s12 = country + mfg + prod
        checksum = EANService.calculate_checksum(s12)
        return s12 + str(checksum)

    @staticmethod
    def generate_batch_eans(count: int, country_code: Optional[str] = None, existing_set: Optional[Set[str]] = None) -> List[str]:
        """批量生成指定数量且互不重复的合规 EAN-13 条码列表"""
        seen = set(existing_set or set())
        results = []
        attempts = 0
        max_attempts = count * 30

        while len(results) < count and attempts < max_attempts:
            attempts += 1
            ean = EANService.generate_single_ean(country_code=country_code)
            if ean not in seen:
                seen.add(ean)
                results.append(ean)
        return results


if __name__ == "__main__":
    eans = EANService.generate_batch_eans(5)
    for e in eans:
        print(f"EAN: {e}, Valid: {EANService.validate_ean13(e)}")
