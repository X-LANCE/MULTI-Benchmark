"""QwenVL evaluator with HuggingFace Transformers"""

from transformers import AutoModelForCausalLM, AutoTokenizer
from transformers.generation import GenerationConfig
import re
import pdb
import torch


class QwenVLEvaluator:
    def __init__(self, model_dir="Qwen/Qwen-VL-Chat-Int4",  # "Qwen/Qwen-VL-Chat"
                 max_tokens=200, dtype=None, device_map="cuda:0"):
        self.model_dir = model_dir
        self.sample_params = {
            "max_new_tokens": max_tokens,
            "do_sample": False
        }

        if dtype in ["bf16", "fp16"]:
            dtype_dict = {dtype: True}
        else:
            dtype_dict = {}

        # Use 16bit precision without quantize costs 20G VRAM.
        # Use quantize costs 10G VRAM.

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(self.model_dir, device_map=device_map, trust_remote_code=True, **dtype_dict).eval()
        self.model.generation_config = GenerationConfig.from_pretrained(self.model_dir, trust_remote_code=True)
        if "Int4" not in self.model_dir:
            self.model.generation_config.__dict__.update(self.sample_params)  # customized params on quantized model throws an error
        else:
            self.model.generation_config.do_sample = False

    def prepare_inputs(self, content, image_list=None, image_path=None):
        if image_list:
            match = re.findall("<img_[0-9]+>", content)
            content_prefix = ""
            if len(match) > 0:
                if len(image_list) == 1:
                    content = content.replace(match[0], "")
                    content_prefix += f"<img>{image_list[0]}</img>\n" # align with previous setting
                else:
                    for i, (img_sub, image_path) in enumerate(zip(match, image_list)):
                        content = content.replace(img_sub, f"[IMAGE_{i+1}]")
                        content_prefix += f"Picture {i+1}: <img>{image_path}</img>\n"
            elif len(image_list) > 0:
                # This is the universal setting of parsing one-round dialogue questions.
                # in `get_prompt` we cleared all img tokens in the question. However that's critically fatal in one-image question
                # We need to add the image paths back!
                if len(image_list) == 1:
                    content_prefix += f"<img>{image_list[0]}</img>\n" # align with our previous setting
                else:
                    for i, image_path in enumerate(image_list):
                        content_prefix += f"Picture {i+1}: <img>{image_path}</img>\n"
            content = content_prefix + content
        elif image_path:
            # The reason it literally works is that in multi-round dialogue questions we parse `image_path` and the information doesn't get lost!
            content = f"<img>{image_path}</img>\n" + content  # The surprising bug says that qwen read the images at the head of text inputs.
        # print(content) # debug only
        return content

    def generate_response(self, input):
        if isinstance(input, dict):
            question = input
            message = self.prepare_inputs(question["prompted_content"], image_list=question.get("image_list"))
            response, _ = self.model.chat(self.tokenizer, query=message, history=None)
            return response, message
        elif isinstance(input, tuple):
            # question with multiple images
            assert len(input) == 3, "inp tuple must have 3 elements. (message, image_path, history)"
            # here the image path has been integrated into `message`
            message, image_path, history = input
            message = self.prepare_inputs(message, image_path=image_path)
            response, history = self.model.chat(self.tokenizer, message, history)
            return response, history, message
        else:
            raise ValueError(f"input type not supported: {type(input)}")

    def generate_answer(self, question):
        try:
            if question.get("prompted_content"):
                response, message = self.generate_response(question)
                question["input_message"] = message
                question.pop("prompted_content")
            elif question.get("prompted_content_list"):
                # Processing questions with multiple images in a model of seemingly 1-image support is essential.
                # We consider multiple-rounds chat to send images separately,
                prompted_content_list = question.get("prompted_content_list")
                image_list = question.get("image_list").copy()
                # image_list.append("")
                history = None
                # We have performed merging before feeding the question into LLM, so here they have been aligned
                assert len(prompted_content_list) == len(image_list), f"Length of prompted_content_list and image_list must be the same. \n{question}"
                question["answer_history"] = []
                question["input_message_list"] = []
                for multi_rounds_prompt, image_path in zip(prompted_content_list, image_list):
                    response, history, message = self.generate_response((multi_rounds_prompt, image_path, history))
                    question["answer_history"].append(response)
                    question["input_message_list"].append(message)
                question.pop("prompted_content_list")
            else:
                raise ValueError(f"Question not supported: {question}")
        except:
            response = ""
            torch.cuda.empty_cache()
        question["prediction"] = response
        return question
