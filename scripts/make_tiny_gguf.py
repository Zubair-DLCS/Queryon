"""Creates a tiny random-weight Llama GGUF (a few MB) for testing the llama.cpp
plumbing without downloading a real model. Its output is gibberish by design."""

import sys

import numpy as np
from gguf import GGUFWriter, TokenType

out = sys.argv[1] if len(sys.argv) > 1 else "tiny.gguf"
n_embd, n_head, n_layer, n_ff, ctx = 64, 4, 2, 128, 4096
rng = np.random.default_rng(0)

tokens = ["<unk>", "<s>", "</s>"] + [f"<0x{i:02X}>" for i in range(256)]
words = ["▁" + w for w in "the a of and to in is it that answer question page simple text { } \" : , [ ] 0 1 2 3 true false".split()]
words += list("abcdefghijklmnopqrstuvwxyz{}[]\":,0123456789 ")
tokens += [w for w in dict.fromkeys(words) if w not in tokens]
types = [TokenType.UNKNOWN, TokenType.CONTROL, TokenType.CONTROL] + [TokenType.BYTE] * 256
types += [TokenType.NORMAL] * (len(tokens) - len(types))
n_vocab = len(tokens)

w = GGUFWriter(out, "llama")
w.add_name("tiny-test")
w.add_context_length(ctx)
w.add_embedding_length(n_embd)
w.add_block_count(n_layer)
w.add_feed_forward_length(n_ff)
w.add_head_count(n_head)
w.add_head_count_kv(n_head)
w.add_rope_dimension_count(n_embd // n_head)
w.add_layer_norm_rms_eps(1e-5)
w.add_file_type(0)
w.add_tokenizer_model("llama")
w.add_token_list(tokens)
w.add_token_scores([0.0] * n_vocab)
w.add_token_types(types)
w.add_bos_token_id(1)
w.add_eos_token_id(2)
w.add_unk_token_id(0)
w.add_chat_template(
    "{% for m in messages %}<s>{{ m['role'] }}: {{ m['content'] }}</s>{% endfor %}"
    "{% if add_generation_prompt %}<s>assistant: {% endif %}")


def t(*shape):
    return (rng.standard_normal(shape) * 0.02).astype(np.float32)


w.add_tensor("token_embd.weight", t(n_vocab, n_embd))
for i in range(n_layer):
    p = f"blk.{i}."
    w.add_tensor(p + "attn_norm.weight", np.ones(n_embd, np.float32))
    for n in ("attn_q", "attn_k", "attn_v", "attn_output"):
        w.add_tensor(p + n + ".weight", t(n_embd, n_embd))
    w.add_tensor(p + "ffn_norm.weight", np.ones(n_embd, np.float32))
    w.add_tensor(p + "ffn_gate.weight", t(n_ff, n_embd))
    w.add_tensor(p + "ffn_up.weight", t(n_ff, n_embd))
    w.add_tensor(p + "ffn_down.weight", t(n_embd, n_ff))
w.add_tensor("output_norm.weight", np.ones(n_embd, np.float32))
w.add_tensor("output.weight", t(n_vocab, n_embd))
w.write_header_to_file()
w.write_kv_data_to_file()
w.write_tensors_to_file()
w.close()
print("wrote", out, n_vocab, "tokens")
