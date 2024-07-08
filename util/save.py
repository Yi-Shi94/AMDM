import torch

def save_weight(model, model_path):
    wtype = model_path.split('.')[-1].strip()
    if wtype == 'pth':
        torch.save(model.cpu().state_dict(), model_path)
    elif wtype == 'pt':
        torch.save(model.cpu(), model_path)
    else:
        torch.save(model.cpu(), model_path)
