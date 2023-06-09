import torch
import torch.nn as nn
from torch import Tensor
import torch.nn.functional as F


# WeightedLayerPooling: Use Intermediate Layer's Embedding
class WeightedLayerPooling(nn.Module):
    def __init__(self, num_hidden_layers, layer_start: int = 4, layer_weights = None):
        super(WeightedLayerPooling, self).__init__()
        self.layer_start = layer_start
        self.num_hidden_layers = num_hidden_layers
        self.layer_weights = layer_weights if layer_weights is not None \
            else nn.Parameter(
                torch.tensor([1] * (num_hidden_layers+1 - layer_start), dtype=torch.float)
            )

    def forward(self, features) -> Tensor:
        ft_all_layers = features['all_layer_embeddings']

        all_layer_embedding = torch.stack(ft_all_layers)
        all_layer_embedding = all_layer_embedding[self.layer_start:, :, :, :]

        weight_factor = self.layer_weights.unsqueeze(-1).unsqueeze(-1).unsqueeze(-1).expand(all_layer_embedding.size())
        weighted_average = (weight_factor*all_layer_embedding).sum(dim=0) / self.layer_weights.sum()

        features.update({'token_embeddings': weighted_average})
        return features


# Attention pooling
class AttentionPooling(nn.Module):
    """
    Reference from => <A STRUCTURED SELF-ATTENTIVE SENTENCE EMBEDDING>
    """
    def __init__(self, in_dim):
        super().__init__()
        self.attention = nn.Sequential(
           nn.Linear(in_dim, in_dim),
           nn.LayerNorm(in_dim),
           nn.GELU(),
           nn.Linear(in_dim, 1),
        )

    def forward(self, last_hidden_state, attention_mask) -> Tensor:
        w = self.attention(last_hidden_state).float()
        w[attention_mask == 0] = float('-inf')
        w = torch.softmax(w, 1)
        attention_embeddings = torch.sum(w * last_hidden_state, dim=1)
        return attention_embeddings


# Mean Pooling
class MeanPooling(nn.Module):
    def __init__(self):
        super(MeanPooling, self).__init__()

    @staticmethod
    def forward(self, last_hidden_state, attention_mask) -> Tensor:
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
        sum_embeddings = torch.sum(last_hidden_state * input_mask_expanded, 1)
        sum_mask = input_mask_expanded.sum(1)
        sum_mask = torch.clamp(sum_mask, min=1e-9)
        mean_embeddings = sum_embeddings / sum_mask
        return mean_embeddings


# Convolution Pooling
# for filtering unwanted feature such as Toxicity Text, Negative Comment...etc
class ConvPooling(nn.Module):
    """
    Reference from => https://www.kaggle.com/code/rhtsingh/utilizing-transformer-representations-efficiently
    kernel_size: similar as window size
    """
    def __init__(self, feature_size: int, kernel_size: int, padding_size: int):
        super().__init__()
        self.feature_size = feature_size
        self.kernel_size = kernel_size
        self.padding_size = padding_size
        self.convolution = nn.Sequential(
            nn.Conv1d(self.feature_size, 256, kernel_size=self.kernel_size, padding=self.padding_size),
            nn.ReLU(),
            nn.Conv1d(256, 1, kernel_size=kernel_size, padding=padding_size),
        )

    def forward(self, last_hidden_state: Tensor) -> Tensor:
        embeddings = last_hidden_state.permute(0, 2, 1) # (batch_size, feature_size, seq_len)
        logit, _ = torch.max(self.convolution(embeddings), 2)
        return logit


# LSTM Pooling
class LSTMPooling(nn.Module):
    def __int__(self, num_layers: int, hidden_size: int, hidden_dim_lstm):
        super().__init__()
        self.num_hidden_layers = num_layers
        self.hidden_size = hidden_size
        self.hidden_size = hidden_size
        self.hidden_dim_lstm = hidden_dim_lstm
        self.lstm = nn.LSTM(
            self.hidden_size,
            self.hidden_dim_lstm,
            batch_first=True
        )
        self.dropout = nn.Dropout(0.1)

    def forward(self, all_hidden_states: list[Tensor]) -> Tensor:
        hidden_states = torch.stack([all_hidden_states[layer_i][:, 0].squeeze()\
                                    for layer_i in range(1, self.num_hidden_layers)], dim=1)
        hidden_states = hidden_states.view(-1, self.num_hidden_layers, self.hidden_size)
        out, _ = self.lstm(hidden_states, None)
        out = self.dropout(out[:, -1, :])
        return out
