"""
Lab #3: Baseline Chatbot vs ReAct Agent
Học viên hoàn thiện các mục TODO để hoàn thành bài lab.
"""

import json
import re
from tools import TOOL_DEFINITIONS, TOOL_MAP, get_flight_info, get_weather_forecast


SYSTEM_PROMPT = """Bạn là một ReAct Agent thông minh hỗ trợ khách hàng Vingroup.
Bạn chỉ sử dụng các công cụ sau:
{tools}

Quy trình trả lời bắt buộc:
Thought: <Suy nghĩ bước tiếp theo>
Action: {{"name": "<tên tool>", "args": {{<tham số>}}}}
Observation: <Kết quả từ tool>
... (Lặp lại cho tới khi có đủ dữ liệu)
Final Answer: <Câu trả lời hoàn chỉnh cho khách hàng>
"""


class ChatbotBaseline:
    """Baseline LLM Chatbot (Không sử dụng ReAct Loop hay Tools)"""

    def query(self, user_input: str) -> dict:
        return {
            "status": "success",
            "answer": f"[Chatbot Baseline] Trả lời cho: {user_input}",
            "tool_calls": []
        }


class ReActAgent:
    """ReAct Agent có sử dụng Thought-Action-Observation Loop"""

    def __init__(self, max_iterations: int = 5):
        self.max_iterations = max_iterations
        self.trace = []

    def _parse_user_input(self, user_input: str):
        """
        Phân tích câu hỏi của người dùng để lấy:
        - sân bay đi
        - sân bay đến
        - giá vé tối đa
        - thành phố cần xem thời tiết
        """

        origin = None
        destination = None
        max_price = None
        weather_city = None

        # Tìm dạng "từ HAN đi SGN"
        flight_match = re.search(
            r"từ\s+([A-Za-z]{3})\s+đi\s+([A-Za-z]{3})",
            user_input,
            re.IGNORECASE
        )

        if flight_match:
            origin = flight_match.group(1).upper()
            destination = flight_match.group(2).upper()

        # Tìm giá dạng "dưới 2 triệu", "dưới 2.000.000"
        price_match = re.search(
            r"dưới\s+([\d.,]+)\s*(triệu|tr|đ|vnd)?",
            user_input,
            re.IGNORECASE
        )

        if price_match:
            price = price_match.group(1).replace(".", "").replace(",", "")
            price = float(price)

            unit = price_match.group(2)

            if unit and unit.lower() in ["triệu", "tr"]:
                price *= 1_000_000

            max_price = int(price)

        # Lấy mã sân bay 3 ký tự trong phần câu hỏi về thời tiết.
        weather_part = re.search(r"thời tiết(.+)", user_input, re.IGNORECASE)
        if weather_part:
            weather_codes = re.findall(r"\b[A-Za-z]{3}\b", weather_part.group(1))
            if weather_codes:
                weather_city = weather_codes[-1].upper()

        # Nếu không tìm thấy thành phố thời tiết,
        # sử dụng điểm đến của chuyến bay
        if weather_city is None and "thời tiết" in user_input.lower():
            weather_city = destination

        return {
            "origin": origin,
            "destination": destination,
            "max_price": max_price,
            "weather_city": weather_city
        }

    def _find_tool(self, possible_names):
        """
        Tìm tool trong TOOL_MAP.
        Cho phép một tool có nhiều cách đặt tên.
        """

        for name in possible_names:
            if name in TOOL_MAP:
                return name, TOOL_MAP[name]

        return None, None

    def _execute_tool(self, action):
        """
        Thực thi tool dựa trên Action.
        """

        tool_name = action["name"]
        args = action.get("args", {})

        if tool_name not in TOOL_MAP:
            return f"Tool '{tool_name}' không tồn tại."

        try:
            tool = TOOL_MAP[tool_name]
            result = tool(**args)
            return result

        except TypeError:
            # Một số tool có thể sử dụng positional arguments
            try:
                tool = TOOL_MAP[tool_name]
                result = tool(*args.values())
                return result
            except Exception as e:
                return f"Lỗi khi thực thi tool: {str(e)}"

        except Exception as e:
            return f"Lỗi khi thực thi tool: {str(e)}"

    def _create_final_answer(self, user_input, flight_result, weather_result):
        """
        Tổng hợp kết quả từ các tool thành câu trả lời cuối cùng.
        """

        answer = []

        if flight_result is not None:
            answer.append("✈️ Thông tin chuyến bay:")
            answer.append(str(flight_result))

        if weather_result is not None:
            answer.append("\n🌤️ Thông tin thời tiết:")
            if isinstance(weather_result, dict) and "temperature_c" in weather_result:
                answer.append(
                    f"{weather_result.get('city', '')}: "
                    f"{weather_result['temperature_c']}°C, "
                    f"{weather_result.get('condition', '')}. "
                    f"{weather_result.get('recommendation', '')}"
                )
            else:
                answer.append(str(weather_result))

            answer.append(
                "\n👕 Gợi ý: Bạn nên kiểm tra nhiệt độ và tình trạng mưa "
                "trước khi đi để lựa chọn quần áo phù hợp."
            )

        if not answer:
            return (
                "Xin lỗi, tôi chưa thể xử lý yêu cầu vì không tìm thấy "
                "công cụ phù hợp."
            )

        return "\n".join(answer)

    def run(self, user_input: str) -> dict:
        self.trace = []

        # Phân tích câu hỏi
        parsed = self._parse_user_input(user_input)

        flight_result = None
        weather_result = None
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1

            # Bước 1: Tìm chuyến bay nếu có thông tin chuyến bay
            if (
                flight_result is None
                and parsed["origin"] is not None
                and parsed["destination"] is not None
            ):

                thought = (
                    "Người dùng muốn tìm chuyến bay từ "
                    f"{parsed['origin']} đến {parsed['destination']}. "
                    "Tôi cần sử dụng công cụ tìm thông tin chuyến bay."
                )

                tool_name, tool = self._find_tool([
                    "get_flight_info",
                    "flight_info",
                    "flight_search"
                ])

                if tool_name is None:
                    observation = "Không tìm thấy tool tìm chuyến bay."

                    self.trace.append({
                        "iteration": iteration,
                        "thought": thought,
                        "observation": observation
                    })

                    flight_result = observation
                    continue

                args = {
                    "origin": parsed["origin"],
                    "destination": parsed["destination"]
                }

                # Chỉ truyền max_price nếu người dùng có yêu cầu
                if parsed["max_price"] is not None:
                    args["max_price"] = parsed["max_price"]

                action = {
                    "name": tool_name,
                    "args": args
                }

                observation = self._execute_tool(action)

                self.trace.append({
                    "iteration": iteration,
                    "thought": thought,
                    "action": action,
                    "observation": observation
                })

                flight_result = observation

                continue

            # Bước 2: Tìm thời tiết
            if (
                weather_result is None
                and parsed["weather_city"] is not None
            ):

                thought = (
                    f"Tôi đã có thông tin chuyến bay. "
                    f"Tiếp theo cần kiểm tra thời tiết tại "
                    f"{parsed['weather_city']} để đưa ra gợi ý trang phục."
                )

                tool_name, tool = self._find_tool([
                    "get_weather_forecast",
                    "weather_forecast",
                    "weather"
                ])

                if tool_name is None:
                    observation = "Không tìm thấy tool dự báo thời tiết."

                    self.trace.append({
                        "iteration": iteration,
                        "thought": thought,
                        "observation": observation
                    })

                    weather_result = observation
                    continue

                action = {
                    "name": tool_name,
                    "args": {
                        "city_code": parsed["weather_city"]
                    }
                }

                # Thực thi weather tool
                observation = self._execute_tool(action)

                self.trace.append({
                    "iteration": iteration,
                    "thought": thought,
                    "action": action,
                    "observation": observation
                })

                weather_result = observation

                continue

            iteration -= 1
            break

        if flight_result is None and weather_result is None:
            final_answer = (
                "Chính sách đổi trả vé máy bay Vinpearl phụ thuộc vào điều kiện "
                "của từng loại vé. Vui lòng kiểm tra điều kiện vé khi đặt."
            )
            self.trace.append({
                "iteration": 1,
                "thought": "Đây là câu hỏi FAQ, không cần gọi tool.",
                "step": "final_answer"
            })
            return {
                "status": "completed",
                "iterations": 1,
                "answer": final_answer,
                "trace": self.trace
            }

        if iteration >= self.max_iterations and (
            (flight_result is not None and weather_result is None)
            or (flight_result is None and weather_result is not None)
        ):
            return {
                "status": "max_iterations_reached",
                "iterations": iteration,
                "answer": "Không thể hoàn thành trong số bước tối đa.",
                "trace": self.trace
            }

        # Tạo Final Answer
        final_answer = self._create_final_answer(
            user_input,
            flight_result,
            weather_result
        )

        if flight_result is not None and weather_result is not None:
            self.trace.append({
                "iteration": iteration + 1,
                "thought": "Đã thu thập đủ dữ liệu và tạo câu trả lời cuối cùng.",
                "step": "final_answer"
            })
            result_iterations = iteration + 1
        else:
            result_iterations = iteration

        return {
            "status": "completed",
            "iterations": result_iterations,
            "answer": final_answer,
            "trace": self.trace
        }


def main():
    user_query = (
        "Tìm cho tôi chuyến bay từ HAN đi SGN dưới 2 triệu, "
        "rồi cho biết thời tiết SGN nên mặc gì?"
    )

    print("=== RUNNING CHATBOT BASELINE ===")

    chatbot = ChatbotBaseline()

    print(chatbot.query(user_query))

    print("\n=== RUNNING REACT AGENT ===")

    agent = ReActAgent(max_iterations=5)

    result = agent.run(user_query)

    print("Result:", result)

    print(
        "Trace Log:",
        json.dumps(
            agent.trace,
            indent=2,
            ensure_ascii=False,
            default=str
        )
    )


if __name__ == "__main__":
    main()