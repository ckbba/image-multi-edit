from test_backend import client
import segmentation

def test_force_sam_bypasses_recognition_cache(client,monkeypatch):
 monkeypatch.setattr(segmentation,'cached_hit',lambda *a:{'mask_id':'cached','label':'海报'})
 monkeypatch.setattr(segmentation,'select',lambda *a:{'candidates':[{'id':'local'}],'cached':False})
 response=client.post('/api/segmentation/select',json={'image_id':'fixture','x':.5,'y':.5,'force_sam':True})
 assert response.status_code==200
 assert response.json()['candidates'][0]['id']=='local'
