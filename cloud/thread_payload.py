"""Keep generated image bytes out of text-history transport copies."""

def for_web(thread):
    result = dict(thread)
    turns = []
    for turn in thread.get('turns') or []:
        items = []
        for item in turn.get('items') or []:
            copy = dict(item)
            image = copy.get('result')
            if copy.get('type') == 'imageGeneration' and isinstance(image, str) and len(image) > 4096:
                copy.pop('result')
                copy['bridgeImageDataOmitted'] = True
            items.append(copy)
        turns.append(dict(turn, items=items))
    result['turns'] = turns
    return result
