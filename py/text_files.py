import os
import folder_paths
import json
from server import PromptServer
import glob
from aiohttp import web


def get_allowed_dirs():
    dir = os.path.abspath(os.path.join(__file__, "../../user"))
    file = os.path.join(dir, "text_file_dirs.json")
    with open(file, "r") as f:
        return json.loads(f.read())


def get_valid_dirs():
    return get_allowed_dirs().keys()


def get_dir_from_name(name):
    dirs = get_allowed_dirs()
    if name not in dirs:
        raise KeyError(name + " dir not found")

    path = dirs[name]
    path = path.replace("$input", folder_paths.get_input_directory())
    path = path.replace("$output", folder_paths.get_output_directory())
    path = path.replace("$temp", folder_paths.get_temp_directory())
    return path


def is_child_dir(parent_path, child_path):
    parent_path = os.path.abspath(parent_path)
    child_path = os.path.abspath(child_path)
    return os.path.commonpath([parent_path]) == os.path.commonpath([parent_path, child_path])


def get_real_path(dir):
    dir = dir.replace("/**/", "/")
    dir = os.path.abspath(dir)
    dir = os.path.split(dir)[0]
    return dir


@PromptServer.instance.routes.get("/pysssss/text-file/{name}")
async def get_files(request):
    name = request.match_info["name"]
    dir = get_dir_from_name(name)
    recursive = "/**/" in dir
    # Ugh cant use root_path on glob... lazy hack..
    pre = get_real_path(dir)

    files = list(map(lambda t: os.path.relpath(t, pre),
                     glob.glob(dir, recursive=recursive)))

    if len(files) == 0:
        files = ["[none]"]
    return web.json_response(files)


def get_file(root_dir, file):
    if file == "[none]" or not file or not file.strip():
        raise ValueError("No file")

    root_dir = get_dir_from_name(root_dir)
    root_dir = get_real_path(root_dir)
    if not os.path.exists(root_dir):
        os.mkdir(root_dir)
    full_path = os.path.join(root_dir, file)

    file_dir = os.path.dirname(full_path)
    if file_dir and not os.path.exists(file_dir):
        os.makedirs(file_dir, exist_ok=True)

    if not is_child_dir(root_dir, full_path):
        raise ReferenceError()

    return full_path


class TextFileNode:
    RETURN_TYPES = ("STRING",)
    CATEGORY = "utils"

    @classmethod
    def VALIDATE_INPUTS(self, root_dir, file, **kwargs):
        if file == "[none]" or not file or not file.strip():
            return True
        get_file(root_dir, file)
        return True

    def load_text(self, **kwargs):
        self.file = get_file(kwargs["root_dir"], kwargs["file"])
        with open(self.file, "r") as f:
            return (f.read(), )


class LoadText(TextFileNode):
    @classmethod
    def IS_CHANGED(self, **kwargs):
        return os.path.getmtime(self.file)

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "root_dir": (list(get_valid_dirs()), {}),
                "file": (["[none]"], {
                    "pysssss.binding": [{
                        "source": "root_dir",
                        "callback": [{
                            "type": "set",
                            "target": "$this.disabled",
                            "value": True
                        }, {
                            "type": "fetch",
                            "url": "/pysssss/text-file/{$source.value}",
                            "then": [{
                                "type": "set",
                                "target": "$this.options.values",
                                "value": "$result"
                            }, {
                                "type": "validate-combo"
                            }, {
                                "type": "set",
                                "target": "$this.disabled",
                                "value": False
                            }]
                        }],
                    }]
                })
            },
        }

    FUNCTION = "load_text"


class SaveText(TextFileNode):
    OUTPUT_NODE = True
    
    @classmethod
    def IS_CHANGED(self, **kwargs):
        return float("nan")

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "filename_prefix": ("STRING", {"default": "ComfyUI"}),
                "file_extension": ("STRING", {"default": ".txt"}),
                "append": (["append", "overwrite", "new only"], {}),
                "insert": ("BOOLEAN", {
                    "default": True, "label_on": "new line", "label_off": "none",
                    "pysssss.binding": [{
                        "source": "append",
                        "callback": [{
                            "type": "if",
                            "condition": [{
                                "left": "$source.value",
                                "op": "eq",
                                "right": '"append"'
                            }],
                            "true": [{
                                "type": "set",
                                "target": "$this.disabled",
                                "value": False
                            }],
                            "false": [{
                                "type": "set",
                                "target": "$this.disabled",
                                "value": True
                            }],
                        }]
                    }]
                }),
                "text": ("STRING", {"forceInput": True, "multiline": True})
            },
        }

    FUNCTION = "write_text"

    def write_text(self, filename_prefix, file_extension, text, append, insert):
        # Path Sanitization
        filename_prefix = filename_prefix.replace('\\', '/')
        filename_prefix = filename_prefix.lstrip('/')
        
        output_dir = folder_paths.get_output_directory()
        
        if '/' in filename_prefix:
            subfolder = os.path.dirname(filename_prefix)
            prefix = os.path.basename(filename_prefix)
        else:
            subfolder = ""
            prefix = filename_prefix
            
        destination_dir = os.path.join(output_dir, subfolder)
        os.makedirs(destination_dir, exist_ok=True)
        
        file_name = f"{prefix}{file_extension}"
        self.file = os.path.join(destination_dir, file_name)
        
        if append == "new only" and os.path.exists(self.file):
            raise FileExistsError(
                self.file + " already exists and 'new only' is selected.")
        
        with open(self.file, "a+" if append == "append" else "w", encoding="utf-8") as f:
            is_append = f.tell() != 0
            if is_append and insert:
                f.write("\n")
            f.write(text)

        with open(self.file, "r", encoding="utf-8") as f:
            content = f.read()

        return {"ui": {"files": [{"filename": file_name, "subfolder": subfolder, "type": "output"}]}, "result": (content,)}


NODE_CLASS_MAPPINGS = {
    "LoadText|pysssss": LoadText,
    "SaveText|pysssss": SaveText,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadText|pysssss": "Load Text 🐍",
    "SaveText|pysssss": "Save Text 🐍",
}
