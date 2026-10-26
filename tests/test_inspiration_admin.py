import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '后端代码'))
import auth
import config
import store
from app import app


def image_bytes():
    buf=io.BytesIO()
    Image.new('RGB',(40,60),'purple').save(buf,'PNG')
    return buf.getvalue()


@pytest.fixture
def clients(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    monkeypatch.setattr(config,'MODE','simulation')
    with TestClient(app) as admin, TestClient(app) as member, TestClient(app) as guest:
        user=admin.post('/api/register',json={'email':'owner@example.com','password':'strong-pass-123'}).json()['user']
        member.post('/api/register',json={'email':'member@example.com','password':'strong-pass-123','role':'admin'})
        with store.db() as con:
            con.execute("UPDATE users SET role='admin',email='admin' WHERE id=?",(user['id'],))
        yield admin,member,guest


def test_admin_permissions_and_username_login(clients):
    admin,member,guest=clients
    routes=[('get',''),('get','/items/editorial/image'),('post','/items'),('put','/items/editorial'),
            ('delete','/items/editorial'),('post','/items/editorial/restore'),('post','/categories'),
            ('put','/categories/test'),('delete','/categories/test')]
    for method,path in routes:
        assert getattr(guest,method)('/api/admin/inspiration'+path).status_code==401
        assert getattr(member,method)('/api/admin/inspiration'+path).status_code==403
    assert member.get('/api/me').json()['user']['role']=='user'
    admin.post('/api/logout')
    response=admin.post('/api/login',json={'email':'admin','password':'strong-pass-123'})
    assert response.status_code==200
    assert response.json()['user']['role']=='admin'
    assert admin.get('/api/admin/inspiration').status_code==200
    assert guest.post('/api/register',json={'email':'admin','password':'strong-pass-123'}).status_code==400
    with store.db() as con:
        con.execute("UPDATE users SET role='user' WHERE email='admin'")
    assert admin.get('/api/admin/inspiration').status_code==403


def test_upload_publish_trash_restore_and_categories(clients):
    admin,member,guest=clients
    base='/api/admin/inspiration'
    assert admin.post(base+'/categories',json={'name':'测试分类'}).status_code==201
    assert admin.post(base+'/categories',json={'name':'测试分类'}).status_code==409
    response=admin.post(base+'/items',data={'title':'紫色商品','category':'测试分类','description':'测试简介'},
                        files={'file':('product.png',image_bytes(),'image/png')})
    assert response.status_code==201,response.text
    item_id=response.json()['id']; public=f'/api/inspiration/{item_id}/image'
    assert guest.get(public).status_code==404
    assert admin.get(base+f'/items/{item_id}/image').status_code==200
    body={'title':'紫色商品','category':'测试分类','description':'保存的简介','source':'自己拍摄',
          'source_url':'https://example.com/picture','published':True}
    assert admin.put(base+f'/items/{item_id}',json=body).status_code==200
    assert guest.get(public).status_code==200
    assert member.put(f'/api/inspiration/{item_id}/like',json={'liked':True}).status_code==200
    assert admin.delete(base+'/categories/测试分类').status_code==409
    assert admin.put(base+'/categories/测试分类',json={'name':'重命名分类'}).status_code==200
    assert guest.get('/api/inspiration?category=重命名分类').json()['items'][0]['id']==item_id
    assert admin.delete(base+f'/items/{item_id}').status_code==200
    assert guest.get(public).status_code==404
    assert member.post(f'/api/inspiration/{item_id}/workspace').status_code==404
    assert member.put(f'/api/inspiration/{item_id}/like',json={'liked':True}).status_code==404
    assert admin.delete(base+'/categories/重命名分类').status_code==409
    body['category']='重命名分类'
    assert admin.put(base+f'/items/{item_id}',json=body).status_code==409
    assert admin.post(base+f'/items/{item_id}/restore').status_code==200
    assert guest.get(public).status_code==404
    assert admin.put(base+f'/items/{item_id}',json=body).status_code==200
    assert guest.get(public).status_code==200
    assert guest.get('/api/inspiration?category=重命名分类').json()['items'][0]['like_count']>=1
    assert admin.post(base+'/categories',json={'name':'空分类'}).status_code==201
    assert admin.delete(base+'/categories/空分类').status_code==200
    assert admin.post(base+f'/items/{item_id}/restore').status_code==200
    assert guest.get(public).status_code==200


def test_reject_invalid_upload_and_metadata(clients):
    admin,_,_=clients
    base='/api/admin/inspiration'
    category=admin.get(base).json()['categories'][0]['name']
    for content in (b'invalid image',b'x'*(20*1024*1024+1)):
        response=admin.post(base+'/items',data={'title':'bad','category':category},files={'file':('bad.png',content,'image/png')})
        assert response.status_code==400
    response=admin.post(base+'/items',data={'title':'good','category':'not-created'},files={'file':('ok.png',image_bytes(),'image/png')})
    assert response.status_code==400
    body={'title':'test','category':category,'published':True,'source_url':'javascript:alert(1)'}
    assert admin.put(base+'/items/editorial',json=body).status_code==400
    body['source_url']='https://[invalid'
    assert admin.put(base+'/items/editorial',json=body).status_code==400
    body.update(source_url='',published='false')
    assert admin.put(base+'/items/editorial',json=body).status_code==422
    assert admin.post(base+'/categories',json={'name':'   '}).status_code==400
    assert admin.post(base+'/categories',json={'name':'食品/饮料'}).status_code==400
